"""Model and agent registry with YAML configuration loading."""

import os
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.exceptions import (
    AgentNotFoundError,
    AgentRegistryError,
    ModelNotFoundError,
    PolicyNotFoundError,
    ToolError,
)
from tasksentry.models.base import ModelClient, ModelResponse
from tasksentry.models.fake_model import FakeModel
from tasksentry.models.openai_compat import OpenAICompatibleClient
from tasksentry.tools.registry import ToolRegistry


class CallableModelClient(ModelClient):
    """Wrapper turning a custom Python callable into a ModelClient."""

    def __init__(self, fn: Callable[..., Any], model_name: str = "custom_callable") -> None:
        self.fn = fn
        self.model_name = model_name

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        result = self.fn(messages, tools, **kwargs)
        if isinstance(result, ModelResponse):
            return result
        if isinstance(result, str):
            return ModelResponse(content=result, model=self.model_name)
        if isinstance(result, dict):
            return ModelResponse(
                content=result.get("content"),
                tool_calls=result.get("tool_calls", []),
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                model=result.get("model", self.model_name),
            )
        return ModelResponse(content=str(result), model=self.model_name)


class ModelRegistry:
    """Registry managing available LLM providers, clients, and mock models."""

    def __init__(self) -> None:
        self._models: dict[str, ModelClient] = {}
        # Pre-register default fake models
        fake = FakeModel()
        self._models["fake-model"] = fake
        self._models["fake_model"] = fake

    def register(self, name: str, client: ModelClient) -> None:
        """Register a ModelClient under a given name."""
        self._models[name] = client

    def register_callable(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a custom Python callable as a model."""
        self._models[name] = CallableModelClient(fn, model_name=name)

    def register_openai(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Register an OpenAI-compatible endpoint."""
        client = OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model=model or name,
            timeout=timeout,
        )
        self._models[name] = client

    def get(self, name: str) -> ModelClient:
        """Lookup a model client by name or raise ModelNotFoundError."""
        if name in self._models:
            return self._models[name]

        if name in ("semantic-router", "semantic_router", "router"):
            from tasksentry.models.router import SemanticModelRouter

            self._models[name] = SemanticModelRouter()
            return self._models[name]

        known_prefixes = ("qwen", "llama", "gemma", "ornith", "beam", "mistral", "phi")
        is_ollama_format = (
            ":" in name
            or "ollama" in name.lower()
            or any(name.startswith(p) for p in known_prefixes)
        )
        if is_ollama_format:
            from tasksentry.models.ollama import OllamaClient

            self._models[name] = OllamaClient(model=name)
            return self._models[name]

        raise ModelNotFoundError(f"Model '{name}' is not registered.")

    def has(self, name: str) -> bool:
        if name in self._models:
            return True
        if name in ("semantic-router", "semantic_router", "router"):
            return True
        known_prefixes = ("qwen", "llama", "gemma", "ornith", "beam", "mistral", "phi")
        return (
            ":" in name
            or "ollama" in name.lower()
            or any(name.startswith(p) for p in known_prefixes)
        )


class PolicyDefinition(BaseModel):
    """Execution policy specification for an agent."""

    model_config = ConfigDict(extra="ignore")

    name: str = "default"
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_wall_time_seconds: float | None = None
    risk_policy: dict[str, Any] = Field(default_factory=dict)


class AgentDefinition(BaseModel):
    """Declarative specification of an agent in agents.yaml."""

    model_config = ConfigDict(extra="ignore")

    name: str
    model: str
    tools: list[str] = Field(default_factory=list)
    system_prompt_file: str | None = None
    system_prompt: str | None = None
    policy: str | None = None
    policy_overrides: dict[str, Any] = Field(default_factory=dict)


class ResolvedAgent(BaseModel):
    """Fully validated and resolved agent runtime metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    name: str
    model_client: ModelClient
    tools: list[str]
    system_prompt: str
    policy: PolicyDefinition


def _load_yaml(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        import yaml  # type: ignore[import-untyped]

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except ImportError:
        return {}


class AgentRegistry:
    """Registry managing agent specifications, policies, and resolution."""

    def __init__(self, model_registry: ModelRegistry | None = None) -> None:
        self.model_registry = model_registry or ModelRegistry()
        self._agents: dict[str, AgentDefinition] = {}
        self._policies: dict[str, PolicyDefinition] = {}

        # Default fallback policy
        self.register_policy(PolicyDefinition(name="default"))

    def register_agent(self, agent: AgentDefinition) -> None:
        self._agents[agent.name] = agent

    def register_policy(self, policy: PolicyDefinition) -> None:
        self._policies[policy.name] = policy

    def load_from_files(
        self,
        agents_path: str = "agents/agents.yaml",
        policies_path: str = "agents/policies.yaml",
    ) -> None:
        """Load agents and policies from YAML files."""
        if os.path.isfile(policies_path):
            pol_data = _load_yaml(policies_path)
            raw_policies = pol_data.get("policies", pol_data)
            for name, cfg in raw_policies.items():
                if isinstance(cfg, dict):
                    self.register_policy(PolicyDefinition(name=name, **cfg))

        if os.path.isfile(agents_path):
            ag_data = _load_yaml(agents_path)
            raw_agents = ag_data.get("agents", ag_data)
            for name, cfg in raw_agents.items():
                if isinstance(cfg, dict):
                    self.register_agent(AgentDefinition(name=name, **cfg))

    def resolve(
        self,
        agent_name: str,
        tool_registry: ToolRegistry | None = None,
        model_registry: ModelRegistry | None = None,
        policy_override: dict[str, Any] | None = None,
    ) -> ResolvedAgent:
        """Resolve an agent name into a fully validated ResolvedAgent."""
        if agent_name not in self._agents:
            raise AgentNotFoundError(f"Agent '{agent_name}' was not found in the agent registry.")

        agent_def = self._agents[agent_name]
        m_reg = model_registry or self.model_registry

        # Check model exists
        if not m_reg.has(agent_def.model):
            raise ModelNotFoundError(
                f"Model '{agent_def.model}' required by agent '{agent_name}' is not registered."
            )
        client = m_reg.get(agent_def.model)

        # Check policy exists
        pol_name = agent_def.policy or "default"
        if pol_name not in self._policies:
            raise PolicyNotFoundError(
                f"Policy '{pol_name}' required by agent '{agent_name}' was not found."
            )
        base_policy = self._policies[pol_name]

        # Apply policy overrides
        if agent_def.policy_overrides or policy_override:
            merged_dict = base_policy.model_dump()
            if agent_def.policy_overrides:
                merged_dict.update(agent_def.policy_overrides)
            if policy_override:
                merged_dict.update(policy_override)
            effective_policy = PolicyDefinition(**merged_dict)
        else:
            effective_policy = base_policy

        # Check tool validation if tool registry provided
        if tool_registry is not None:
            for t_name in agent_def.tools:
                if not tool_registry.has(t_name):
                    raise ToolError(
                        f"Tool '{t_name}' required by agent '{agent_name}' is not registered."
                    )

        # Load system prompt
        prompt = agent_def.system_prompt or ""
        if agent_def.system_prompt_file:
            if not os.path.isfile(agent_def.system_prompt_file):
                err_msg = (
                    f"Prompt file '{agent_def.system_prompt_file}' "
                    f"for agent '{agent_name}' not found."
                )
                raise AgentRegistryError(err_msg)
            with open(agent_def.system_prompt_file, encoding="utf-8") as f:
                prompt = f.read()

        return ResolvedAgent(
            name=agent_name,
            model_client=client,
            tools=agent_def.tools,
            system_prompt=prompt,
            policy=effective_policy,
        )
