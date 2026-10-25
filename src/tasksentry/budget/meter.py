"""Resource meter for real-time tracking of token, cost, call, and latency metrics."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UsageMeter(BaseModel):
    """Mutable accumulator of consumed task resources."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    llm_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    wall_time_seconds: float = Field(default=0.0, ge=0.0)

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Add input and output tokens."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token increments must be non-negative")
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens

    def add_cost(self, cost_usd: float) -> None:
        """Add dollar cost."""
        if cost_usd < 0:
            raise ValueError("Cost increment must be non-negative")
        self.cost_usd += cost_usd

    def increment_llm_calls(self, count: int = 1) -> None:
        """Increment LLM call counter."""
        self.llm_calls += max(0, count)

    def increment_tool_calls(self, count: int = 1, retried: bool = False) -> None:
        """Increment tool call counter and optional retry counter."""
        self.tool_calls += max(0, count)
        if retried:
            self.retries += max(0, count)

    def summary(self) -> dict[str, Any]:
        """Return a dictionary summary of all tracked usage metrics."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "retries": self.retries,
            "wall_time_seconds": round(self.wall_time_seconds, 4),
        }
