"""Unit tests for agent registry and resolution."""

import os

import pytest
from pydantic import BaseModel

from tasksentry.exceptions import (
    AgentNotFoundError,
    AgentRegistryError,
    ModelNotFoundError,
    PolicyNotFoundError,
    ToolError,
)
from tasksentry.models.fake_model import FakeModel
from tasksentry.models.registry import (
    AgentDefinition,
    AgentRegistry,
    ModelRegistry,
    PolicyDefinition,
)
from tasksentry.tools.registry import Tool, ToolRegistry


def test_agent_registry_valid_resolution(tmp_path: os.PathLike[str]) -> None:
    prompt_file = os.path.join(str(tmp_path), "prompt.md")
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write("You are an expert agent.")

    m_reg = ModelRegistry()
    m_reg.register("fake-model", FakeModel())

    t_reg = ToolRegistry()

    def dummy() -> str:
        return "ok"

    t_reg.register(Tool(name="read_file", input_model=BaseModel, callable=dummy))

    a_reg = AgentRegistry(model_registry=m_reg)
    a_reg.register_policy(
        PolicyDefinition(name="custom-policy", max_llm_calls=5, max_cost_usd=0.20)
    )
    a_reg.register_agent(
        AgentDefinition(
            name="test-agent",
            model="fake-model",
            tools=["read_file"],
            system_prompt_file=prompt_file,
            policy="custom-policy",
        )
    )

    resolved = a_reg.resolve("test-agent", tool_registry=t_reg)
    assert resolved.name == "test-agent"
    assert resolved.system_prompt == "You are an expert agent."
    assert resolved.policy.max_llm_calls == 5
    assert resolved.tools == ["read_file"]


def test_agent_registry_missing_agent() -> None:
    a_reg = AgentRegistry()
    with pytest.raises(AgentNotFoundError):
        a_reg.resolve("non-existent-agent")


def test_agent_registry_missing_model() -> None:
    a_reg = AgentRegistry()
    a_reg.register_agent(
        AgentDefinition(name="bad-model-agent", model="unregistered-model")
    )
    with pytest.raises(ModelNotFoundError):
        a_reg.resolve("bad-model-agent")


def test_agent_registry_missing_policy() -> None:
    a_reg = AgentRegistry()
    a_reg.register_agent(
        AgentDefinition(
            name="bad-policy-agent",
            model="fake-model",
            policy="non-existent-policy",
        )
    )
    with pytest.raises(PolicyNotFoundError):
        a_reg.resolve("bad-policy-agent")


def test_agent_registry_missing_tool() -> None:
    t_reg = ToolRegistry()
    a_reg = AgentRegistry()
    a_reg.register_agent(
        AgentDefinition(
            name="missing-tool-agent",
            model="fake-model",
            tools=["missing_tool"],
        )
    )
    with pytest.raises(ToolError):
        a_reg.resolve("missing-tool-agent", tool_registry=t_reg)


def test_agent_registry_policy_override() -> None:
    a_reg = AgentRegistry()
    a_reg.register_policy(
        PolicyDefinition(name="base-policy", max_llm_calls=10, max_tokens=1000)
    )
    a_reg.register_agent(
        AgentDefinition(
            name="overridden-agent",
            model="fake-model",
            policy="base-policy",
            policy_overrides={"max_llm_calls": 25},
        )
    )

    resolved = a_reg.resolve("overridden-agent")
    assert resolved.policy.max_llm_calls == 25
    assert resolved.policy.max_tokens == 1000


def test_agent_registry_missing_prompt_file() -> None:
    a_reg = AgentRegistry()
    a_reg.register_agent(
        AgentDefinition(
            name="bad-prompt-agent",
            model="fake-model",
            system_prompt_file="missing_prompts/does_not_exist.md",
        )
    )
    with pytest.raises(AgentRegistryError):
        a_reg.resolve("bad-prompt-agent")
