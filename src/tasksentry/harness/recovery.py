"""Recovery engine and policies for automated failure mitigation and context compaction."""

import random
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.core.events import (
    CHECKPOINT,
    COMPRESS,
    ESCALATE,
    REPLAN,
    RETRY,
    VERIFICATION_FAILED,
    Event,
)


class RecoveryAction(StrEnum):
    """Actions directed by the recovery engine upon detecting execution failures or limits."""

    RETRY = "retry"
    SCHEMA_CORRECTION = "schema_correction"
    FORCE_REPLAN = "force_replan"
    COMPACT_CONTEXT = "compact_context"
    WARN_BUDGET = "warn_budget"
    STOP_BUDGET = "stop_budget"
    PAUSE_APPROVAL = "pause_approval"
    REJECT_COMPLETION = "reject_completion"
    ESCALATE = "escalate"
    CONTINUE = "continue"


class RecoveryDecision(BaseModel):
    """Structured decision returned by the recovery engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: RecoveryAction
    reason: str
    message: str
    backoff_seconds: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


def compute_backoff(
    attempt: int,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    jitter: bool = True,
) -> float:
    """Calculate exponential backoff delay with optional jitter.

    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
    """
    exp_factor = 2 ** max(0, attempt - 1)
    delay = min(max_delay, base_delay * exp_factor)
    if jitter:
        # Uniform jitter between 0.8 and 1.2 * delay
        jitter_factor = 0.8 + 0.4 * random.random()
        delay = delay * jitter_factor
    return float(max(0.0, round(delay, 4)))


def compact_context(
    messages: list[dict[str, Any]],
    *,
    goal: str,
    active_milestone: str | None = None,
    facts: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    max_retained_history: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compact agent conversation history while preserving essential state.

    Preserves:
    - Task goal
    - Active milestone
    - Verified facts
    - Current plan
    - Latest failure (if present)
    - Most recent execution messages

    Filters out:
    - Duplicate tool outputs
    - Resolved error messages
    """
    latest_failure = None
    seen_outputs: set[str] = set()
    cleaned_recent: list[dict[str, Any]] = []

    # Identify latest failure and deduplicate tool outputs
    for msg in reversed(messages):
        role = msg.get("role", "")
        content = str(msg.get("content", ""))

        if latest_failure is None and (
            msg.get("is_error") or "error" in content.lower() or "failed" in content.lower()
        ):
            latest_failure = content

        if role == "tool":
            content_key = content.strip()[:100]
            if content_key in seen_outputs:
                continue
            seen_outputs.add(content_key)

        cleaned_recent.append(msg)
        if len(cleaned_recent) >= max_retained_history:
            break

    cleaned_recent.reverse()

    checkpoint = {
        "timestamp": time.time(),
        "goal": goal,
        "active_milestone": active_milestone,
        "facts": facts or {},
        "plan": plan or {},
        "latest_failure": latest_failure,
        "original_message_count": len(messages),
        "compacted_message_count": len(cleaned_recent) + 1,
    }

    summary_content = (
        f"--- CONTEXT CHECKPOINT ---\n"
        f"Goal: {goal}\n"
        f"Active Milestone: {active_milestone or 'None'}\n"
        f"Verified Facts: {facts or {}}\n"
        f"Latest Status / Failure: {latest_failure or 'None'}\n"
        f"--- RESUMING WITH RECENT MESSAGES ---"
    )

    compacted = [{"role": "system", "content": summary_content}, *cleaned_recent]
    return compacted, checkpoint


class RecoveryEngine:
    """Manages failure recovery policies, replan triggers, and backoff scheduling."""

    def __init__(
        self,
        *,
        max_tool_failures_before_replan: int = 3,
        max_zero_progress_steps_before_replan: int = 3,
        max_context_messages: int = 12,
        base_backoff_seconds: float = 0.5,
    ) -> None:
        self.max_tool_failures_before_replan = max_tool_failures_before_replan
        self.max_zero_progress_steps_before_replan = max_zero_progress_steps_before_replan
        self.max_context_messages = max_context_messages
        self.base_backoff_seconds = base_backoff_seconds

        self._tool_consecutive_failures: dict[str, int] = {}
        self._consecutive_zero_progress: int = 0
        self._retry_attempts: dict[str, int] = {}
        self._events: list[Event] = []

    @property
    def events(self) -> list[Event]:
        """Lifecycle events emitted during recovery."""
        return list(self._events)

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> Event:
        event = Event(type=event_type, message=message, data=data or {})
        self._events.append(event)
        return event

    def record_step_progress(self, apg: float) -> None:
        """Update zero-progress counter based on APG score."""
        if apg <= 0.0:
            self._consecutive_zero_progress += 1
        else:
            self._consecutive_zero_progress = 0

    def record_tool_success(self, tool_name: str) -> None:
        """Clear failure and retry counters for a successfully executed tool."""
        self._tool_consecutive_failures[tool_name] = 0
        self._retry_attempts[tool_name] = 0

    def evaluate_failure(
        self,
        *,
        tool_name: str,
        error_type: str,
        is_transient: bool = False,
        is_validation_error: bool = False,
        validation_errors: list[dict[str, Any]] | None = None,
        is_completion_rejected: bool = False,
        is_unsafe_write: bool = False,
        context_message_count: int = 0,
        blocked_duplicates_count: int = 0,
    ) -> RecoveryDecision:
        """Evaluate failure conditions against recovery policies."""
        # 1. Blocked duplicates escalation (3 strikes)
        if blocked_duplicates_count >= 3:
            msg = f"Task escalated: {blocked_duplicates_count} duplicate actions blocked"
            self._emit(ESCALATE, msg, {"blocked_count": blocked_duplicates_count})
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE,
                reason="three_blocked_duplicates",
                message=msg,
                details={"blocked_count": blocked_duplicates_count},
            )

        # 2. Unsafe write requiring approval
        if is_unsafe_write:
            msg = f"Write action {tool_name!r} requires human approval before proceeding."
            return RecoveryDecision(
                action=RecoveryAction.PAUSE_APPROVAL,
                reason="unsafe_write",
                message=msg,
                details={"tool": tool_name},
            )

        # 3. Model completion claim rejected by verification gate
        if is_completion_rejected:
            msg = "Completion claim rejected: objective verification gates failed."
            self._emit(VERIFICATION_FAILED, msg, {"tool": tool_name})
            return RecoveryDecision(
                action=RecoveryAction.REJECT_COMPLETION,
                reason="verification_failed",
                message=msg,
            )

        # 4. Malformed tool arguments
        if is_validation_error:
            msg = f"Malformed arguments for tool {tool_name!r}. Please correct schema."
            return RecoveryDecision(
                action=RecoveryAction.SCHEMA_CORRECTION,
                reason="malformed_arguments",
                message=msg,
                details={"errors": validation_errors or []},
            )

        # Update failure counters for tool
        failures = self._tool_consecutive_failures.get(tool_name, 0) + 1
        self._tool_consecutive_failures[tool_name] = failures

        # 5. Tool failed 3 times consecutively -> Force Replan
        if failures >= self.max_tool_failures_before_replan:
            msg = f"Tool {tool_name!r} failed {failures} times consecutively. Forcing replan."
            self._emit(REPLAN, msg, {"tool": tool_name, "failures": failures})
            return RecoveryDecision(
                action=RecoveryAction.FORCE_REPLAN,
                reason="repeated_tool_failure",
                message=msg,
                details={"tool": tool_name, "failures": failures},
            )

        # 6. No progress for 3 steps -> Force Replan
        if self._consecutive_zero_progress >= self.max_zero_progress_steps_before_replan:
            msg = (
                f"Zero progress detected for {self._consecutive_zero_progress} steps. "
                "Forcing replan."
            )
            self._emit(REPLAN, msg, {"steps": self._consecutive_zero_progress})
            return RecoveryDecision(
                action=RecoveryAction.FORCE_REPLAN,
                reason="zero_progress",
                message=msg,
                details={"zero_progress_steps": self._consecutive_zero_progress},
            )

        # 7. Context near configured limit -> Compress
        if context_message_count >= self.max_context_messages:
            msg = f"Context length ({context_message_count} messages) near limit. Compacting."
            self._emit(COMPRESS, msg, {"message_count": context_message_count})
            self._emit(CHECKPOINT, "Context compacted into state checkpoint", {})
            return RecoveryDecision(
                action=RecoveryAction.COMPACT_CONTEXT,
                reason="context_near_limit",
                message=msg,
            )

        # 8. Transient failure -> Exponential backoff retry
        if is_transient:
            attempts = self._retry_attempts.get(tool_name, 0) + 1
            self._retry_attempts[tool_name] = attempts
            delay = compute_backoff(attempts, base_delay=self.base_backoff_seconds)
            msg = (
                f"Transient error in {tool_name!r}. Retrying in {delay:.2f}s (attempt {attempts})."
            )
            self._emit(RETRY, msg, {"tool": tool_name, "attempt": attempts, "backoff": delay})
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                reason="transient_error",
                message=msg,
                backoff_seconds=delay,
                details={"attempt": attempts},
            )

        # Default continue with failure message
        return RecoveryDecision(
            action=RecoveryAction.CONTINUE,
            reason="standard_error",
            message=f"Error executing {tool_name}: {error_type}",
        )
