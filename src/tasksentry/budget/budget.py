"""Task budget tracking, limit enforcement, and warning events."""

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from tasksentry.budget.policy import BudgetPolicy
from tasksentry.core.events import (
    BUDGET_EXCEEDED,
    BUDGET_HARD_LIMIT,
    BUDGET_WARNING,
    Event,
)
from tasksentry.exceptions import BudgetExceededError


class Budget(BaseModel):
    """Pydantic v2 budget tracker managing hard and soft execution limits.

    Attributes:
        max_llm_calls: maximum permitted LLM calls (None for unlimited).
        max_tool_calls: maximum permitted tool calls (None for unlimited).
        max_tokens: maximum total token count (input + output).
        max_cost_usd: maximum monetary cost in USD.
        max_wall_time_seconds: maximum elapsed wall clock time in seconds.
        started_at: timestamp when task/budget tracking began.
        expires_at: timestamp when budget deadline expires.
        policy: enforcement rules (hard limits, warning threshold).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    max_llm_calls: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0.0)
    max_wall_time_seconds: float | None = Field(default=None, gt=0.0)

    started_at: float | None = None
    expires_at: float | None = None
    policy: BudgetPolicy = Field(default_factory=BudgetPolicy)

    # Tracked usage fields
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    llm_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    wall_time_seconds: float = Field(default=0.0, ge=0.0)

    _events: list[Event] = PrivateAttr(default_factory=list)
    _event_sink: Callable[[Event], None] | None = PrivateAttr(default=None)
    _warned_dimensions: set[str] = PrivateAttr(default_factory=set)

    @model_validator(mode="after")
    def _init_timing(self) -> "Budget":
        if self.started_at is None:
            self.started_at = time.time()
        if self.expires_at is None and self.max_wall_time_seconds is not None:
            self.expires_at = self.started_at + self.max_wall_time_seconds
        return self

    def set_event_sink(self, sink: Callable[[Event], None] | None) -> None:
        """Set a callback listener for budget lifecycle events."""
        self._event_sink = sink

    @property
    def events(self) -> list[Event]:
        """List of all budget events emitted so far."""
        return list(self._events)

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> Event:
        event = Event(type=event_type, message=message, data=data or {})
        self._events.append(event)
        if self._event_sink is not None:
            self._event_sink(event)
        return event

    def _update_wall_time(self) -> float:
        if self.started_at is not None:
            elapsed = max(0.0, time.time() - self.started_at)
            self.wall_time_seconds = elapsed
            return elapsed
        return self.wall_time_seconds

    def remaining_budget(self) -> dict[str, Any]:
        """Compute remaining resources across all configured limits."""
        self._update_wall_time()
        return {
            "remaining_llm_calls": (
                (self.max_llm_calls - self.llm_calls) if self.max_llm_calls is not None else None
            ),
            "remaining_tool_calls": (
                (self.max_tool_calls - self.tool_calls) if self.max_tool_calls is not None else None
            ),
            "remaining_tokens": (
                (self.max_tokens - self.total_tokens) if self.max_tokens is not None else None
            ),
            "remaining_cost_usd": (
                round(self.max_cost_usd - self.cost_usd, 6)
                if self.max_cost_usd is not None
                else None
            ),
            "remaining_wall_time_seconds": (
                max(0.0, round(self.max_wall_time_seconds - self.wall_time_seconds, 4))
                if self.max_wall_time_seconds is not None
                else None
            ),
        }

    def usage_summary(self) -> dict[str, Any]:
        """Return a structured summary of consumed resources."""
        self._update_wall_time()
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

    def can_afford(
        self,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 0,
        tool_calls: int = 0,
    ) -> bool:
        """Check whether proposed consumption fits within remaining limits.

        Returns:
            True if all limits can accommodate the requested usage, False otherwise.
        """
        self._update_wall_time()
        now = time.time()
        if self.expires_at is not None and now > self.expires_at:
            return False
        if (
            self.max_wall_time_seconds is not None
            and self.wall_time_seconds >= self.max_wall_time_seconds
        ):
            return False
        if self.max_tokens is not None and (self.total_tokens + tokens) > self.max_tokens:
            return False
        if self.max_cost_usd is not None and (self.cost_usd + cost_usd) > self.max_cost_usd:
            return False
        if self.max_llm_calls is not None and (self.llm_calls + llm_calls) > self.max_llm_calls:
            return False
        return not (
            self.max_tool_calls is not None and (self.tool_calls + tool_calls) > self.max_tool_calls
        )

    def _check_warnings_and_limits(self, *, prospective: bool = False) -> None:
        """Evaluate warning (80%) and exceeded (100%) thresholds."""
        self._update_wall_time()
        now = time.time()

        dimensions: list[tuple[str, float, float | None]] = [
            (
                "tokens",
                float(self.total_tokens),
                float(self.max_tokens) if self.max_tokens else None,
            ),
            ("cost_usd", self.cost_usd, self.max_cost_usd),
            (
                "llm_calls",
                float(self.llm_calls),
                float(self.max_llm_calls) if self.max_llm_calls else None,
            ),
            (
                "tool_calls",
                float(self.tool_calls),
                float(self.max_tool_calls) if self.max_tool_calls else None,
            ),
            ("wall_time_seconds", self.wall_time_seconds, self.max_wall_time_seconds),
        ]

        # Check expiration deadline
        if self.expires_at is not None and now > self.expires_at:
            exceeded_msg = (
                f"Task budget expired (deadline exceeded by {now - self.expires_at:.2f}s)"
            )
            self._emit(
                BUDGET_EXCEEDED,
                exceeded_msg,
                {"dimension": "expires_at", "deadline": self.expires_at},
            )
            if self.policy.hard_limits:
                self._emit(BUDGET_HARD_LIMIT, exceeded_msg, {"dimension": "expires_at"})
                raise BudgetExceededError(exceeded_msg)

        warn_ratio = self.policy.warning_threshold
        for name, current, limit in dimensions:
            if limit is None or limit <= 0:
                continue
            ratio = current / limit
            if ratio >= warn_ratio and name not in self._warned_dimensions:
                self._warned_dimensions.add(name)
                self._emit(
                    BUDGET_WARNING,
                    f"Budget warning for {name}: consumed {current}/{limit} ({ratio * 100:.1f}%)",
                    {"dimension": name, "current": current, "limit": limit, "ratio": ratio},
                )

            if ratio >= 1.0:
                msg = f"Budget exceeded for {name}: {current} reached limit {limit}"
                self._emit(
                    BUDGET_EXCEEDED,
                    msg,
                    {"dimension": name, "current": current, "limit": limit, "ratio": ratio},
                )
                if self.policy.hard_limits and (current > limit or prospective):
                    self._emit(
                        BUDGET_HARD_LIMIT,
                        f"Hard budget limit blocked action on {name}",
                        {"dimension": name, "current": current, "limit": limit},
                    )
                    raise BudgetExceededError(msg)

    def check(
        self,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 0,
        tool_calls: int = 0,
    ) -> None:
        """Pre-action budget verification.

        Raises:
            BudgetExceededError: if hard limits are enabled and proposed action would
                exceed any configured limit.
        """
        self._update_wall_time()
        # First check current state
        self._check_warnings_and_limits()

        # Check prospective action
        if not self.can_afford(
            tokens=tokens,
            cost_usd=cost_usd,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
        ):
            msg = (
                "Action cannot be afforded with remaining budget: "
                f"proposed tokens={tokens}, cost={cost_usd}, "
                f"llm_calls={llm_calls}, tool_calls={tool_calls}"
            )
            self._emit(BUDGET_EXCEEDED, msg, {"prospective": True})
            if self.policy.hard_limits:
                self._emit(BUDGET_HARD_LIMIT, msg, {"prospective": True})
                raise BudgetExceededError(msg)

    def record_usage(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 0,
        retries: int = 0,
    ) -> None:
        """Record consumed LLM tokens, cost, and calls.

        Usage is recorded immediately before checking limits to ensure accurate accounting
        even if BudgetExceededError is raised.
        """
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts must be non-negative")
        if cost_usd < 0:
            raise ValueError("Cost must be non-negative")

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.cost_usd += cost_usd
        self.llm_calls += max(0, llm_calls)
        self.retries += max(0, retries)

        self._check_warnings_and_limits()

    def record_tool_call(self, *, retried: bool = False, count: int = 1) -> None:
        """Record one or more tool calls and optional retries."""
        self.tool_calls += max(0, count)
        if retried:
            self.retries += max(0, count)

        self._check_warnings_and_limits()
