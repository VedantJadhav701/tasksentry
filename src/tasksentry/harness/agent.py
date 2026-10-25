"""Agent interfaces and deterministic offline mock agents for CASE harness testing."""

import json
import logging
import re
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from tasksentry.core.state import CanonicalState
from tasksentry.models.base import ModelClient
from tasksentry.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@runtime_checkable
class Agent(Protocol):
    """Protocol implemented by AI agent runners interacting with the TaskSentry harness."""

    def step(
        self,
        canonical_state: CanonicalState,
        history: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Propose the next action given current state, history, and active plan."""
        ...


class ScriptedAgent:
    """Deterministic agent following a preset sequence of actions."""

    def __init__(self, actions: Sequence[dict[str, Any]]) -> None:
        self.actions = list(actions)
        self._index = 0

    def step(
        self,
        canonical_state: CanonicalState,
        history: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the next preset action, or default to complete_task."""
        if self._index < len(self.actions):
            action = self.actions[self._index]
            self._index += 1
            return action
        return {"type": "complete_task"}


class FakeCodingAgent:
    """Simulated coding agent that performs file operations and passes verification gates."""

    def __init__(self, actions: Sequence[dict[str, Any]] | None = None) -> None:
        self._scripted = list(actions) if actions is not None else None
        self._step = 0

    def step(
        self,
        canonical_state: CanonicalState,
        history: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce scripted action or default coding step sequence."""
        if self._scripted is not None:
            if self._step < len(self._scripted):
                act = self._scripted[self._step]
                self._step += 1
                return act
            return {"type": "complete_task"}

        self._step += 1
        if self._step == 1:
            return {
                "type": "tool_call",
                "tool": "echo",
                "arguments": {"text": "initializing task workspace"},
            }
        return {"type": "complete_task"}


class LLMAgent:
    """Autonomous agent that interacts with an underlying LLM (e.g. Ollama, SemanticRouter).

    Constructs prompts, formats tools, and autonomously selects actions or claims task completion.
    """

    def __init__(
        self,
        model_client: ModelClient,
        registry: ToolRegistry | None = None,
        system_prompt: str | None = None,
        budget: Any | None = None,
    ) -> None:
        self.model_client = model_client
        self.registry = registry
        self.budget = budget
        self.system_prompt = system_prompt or (
            "You are a helpful autonomous agent governed by TaskSentry.\n"
            "Your objective is to accomplish the goal safely and efficiently.\n"
            "Select tools when needed to gather facts or modify state.\n"
            "When the goal is satisfied and verified, declare completion.\n"
        )

    def _build_tool_definitions(self) -> list[dict[str, Any]]:
        if not self.registry:
            return []
        tool_defs: list[dict[str, Any]] = []
        for t in self.registry.list_tools():
            schema = t.input_model.model_json_schema() if t.input_model else {"type": "object"}
            tool_defs.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or f"Tool {t.name}",
                        "parameters": schema,
                    },
                }
            )
        return tool_defs

    def step(
        self,
        canonical_state: CanonicalState,
        history: list[dict[str, Any]],
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Propose next action by querying the LLM."""
        tools_spec = self._build_tool_definitions()

        # Build system instruction
        sys_msg = (
            f"{self.system_prompt}\n\n"
            f"Goal: {canonical_state.goal}\n"
            f"Current Known World Facts: {canonical_state.world}\n"
            f"Completed Milestones: {list(canonical_state.milestones)}\n"
            f"Active Plan: {plan.get('active_plan', 'Execute towards goal')}\n"
            "Instructions:\n"
            "- If you need to invoke a tool, call the appropriate tool with arguments.\n"
            "- If the goal is satisfied and verified, respond with: COMPLETE: <summary>\n"
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": sys_msg}]

        # Append recent interaction history (max 8 steps to avoid bloat)
        recent_history = history[-8:] if len(history) > 8 else history
        for item in recent_history:
            role = item.get("role", "user")
            content = str(item.get("content", ""))
            if role in ("assistant", "user", "system", "tool"):
                messages.append({"role": role, "content": content})

        try:
            resp = self.model_client.complete(messages, tools=tools_spec if tools_spec else None)
        except Exception as exc:
            logger.error("LLM completion failed in LLMAgent: %s", exc)
            return {"type": "complete_task", "answer": f"LLM error: {exc}"}

        if self.budget is not None and hasattr(self.budget, "record_usage"):
            self.budget.record_usage(
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                llm_calls=1,
            )

        # 1. Check for native tool calls
        if resp.tool_calls:
            tc = resp.tool_calls[0]
            raw_func = tc.get("function")
            func_meta: dict[str, Any] = raw_func if isinstance(raw_func, dict) else {}
            name: str = str(tc.get("name") or func_meta.get("name") or "")
            args_val = tc.get("arguments") or func_meta.get("arguments") or {}
            args: dict[str, Any]
            if isinstance(args_val, str):
                try:
                    loaded = json.loads(args_val)
                    args = loaded if isinstance(loaded, dict) else {}
                except Exception:
                    args = {}
            elif isinstance(args_val, dict):
                args = dict(args_val)
            else:
                args = {}
            if name:
                return {"type": "tool_call", "tool": name, "arguments": args}

        # 2. Check content for JSON tool call or completion claim
        content = (resp.content or "").strip()

        # Look for markdown JSON block or {"tool": ...}
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                if isinstance(parsed, dict):
                    if "tool" in parsed or "name" in parsed:
                        t_name = parsed.get("tool") or parsed.get("name")
                        t_args = parsed.get("arguments", parsed.get("parameters", {}))
                        return {"type": "tool_call", "tool": t_name, "arguments": t_args}
                    if parsed.get("type") in ("complete_task", "finish"):
                        return dict(parsed)
            except Exception:
                pass

        # 3. Check for completion declaration
        lower_content = content.lower()
        if (
            "complete:" in lower_content
            or "task complete" in lower_content
            or "task is complete" in lower_content
            or "goal achieved" in lower_content
            or not tools_spec
        ):
            return {"type": "complete_task", "answer": content}

        # Fallback to returning completion with model answer
        return {"type": "complete_task", "answer": content}
