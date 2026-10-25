"""Base protocol and response data model for model clients."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ModelResponse(BaseModel):
    """Normalized response returned by a ModelClient."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model: str = ""
    finish_reason: str = "stop"
    raw_response: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class ModelClient(Protocol):
    """Protocol implemented by all model providers and test mocks."""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate a model completion with optional tool calls."""
        ...
