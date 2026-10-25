"""Agent interfaces and deterministic offline mock agents for CASE harness testing."""

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from tasksentry.core.state import CanonicalState


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
