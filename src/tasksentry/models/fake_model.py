"""Deterministic offline mock model client for tests and demos."""

from collections.abc import Callable
from typing import Any

from tasksentry.models.base import ModelClient, ModelResponse


class FakeModel(ModelClient):
    """Deterministic model client for reproducible testing without network dependencies."""

    def __init__(
        self,
        responses: list[ModelResponse | dict[str, Any] | str] | None = None,
        model_name: str = "fake-model",
        custom_handler: (
            Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], ModelResponse] | None
        ) = None,
    ) -> None:
        self.model_name = model_name
        self._responses = list(responses) if responses is not None else []
        self._custom_handler = custom_handler
        self.call_count = 0
        self.history: list[dict[str, Any]] = []

    def queue_response(self, response: ModelResponse | dict[str, Any] | str) -> None:
        """Add a canned response to the queue."""
        self._responses.append(response)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Produce the next queued or deterministic response."""
        self.call_count += 1
        self.history.append({"messages": messages, "tools": tools, "kwargs": kwargs})

        if self._custom_handler is not None:
            return self._custom_handler(messages, tools)

        if self._responses:
            next_resp = self._responses.pop(0)
            if isinstance(next_resp, ModelResponse):
                return next_resp
            if isinstance(next_resp, str):
                return ModelResponse(
                    content=next_resp,
                    input_tokens=len(str(messages)) // 4,
                    output_tokens=len(next_resp) // 4,
                    model=self.model_name,
                    finish_reason="stop",
                )
            if isinstance(next_resp, dict):
                return ModelResponse(
                    content=next_resp.get("content"),
                    tool_calls=next_resp.get("tool_calls", []),
                    input_tokens=next_resp.get("input_tokens", len(str(messages)) // 4),
                    output_tokens=next_resp.get("output_tokens", 10),
                    model=next_resp.get("model", self.model_name),
                    finish_reason=next_resp.get("finish_reason", "stop"),
                    raw_response=next_resp.get("raw_response", {}),
                )

        # Default deterministic fallback
        last_msg = messages[-1].get("content", "") if messages else ""
        return ModelResponse(
            content=f"Fake response to: {last_msg}",
            tool_calls=[],
            input_tokens=20,
            output_tokens=10,
            model=self.model_name,
            finish_reason="stop",
        )
