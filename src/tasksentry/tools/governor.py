"""Tool governor enforcing schema validation, safety, budgets, and loop prevention."""

from collections.abc import Callable, Mapping
from typing import Any

from tasksentry.budget.budget import Budget
from tasksentry.core.contract import SafetyRules
from tasksentry.core.events import (
    BUDGET_EXCEEDED,
    BUDGET_HARD_LIMIT,
    RETRY,
    RETRY_EXEMPTED,
    TOOL_BLOCKED_DUPLICATE,
    TOOL_ERROR,
    TOOL_SUCCESS,
    TOOL_TIMEOUT,
    TOOL_VALIDATION_FAILED,
    Event,
)
from tasksentry.core.state import CanonicalState, action_fingerprint
from tasksentry.exceptions import ToolValidationError
from tasksentry.math.progress import ProgressTracker, RetryExemptions
from tasksentry.tools.registry import ToolRegistry
from tasksentry.tools.sandbox import Sandbox


class ToolGovernor:
    """Central control gate enforcing safety, budget, and anti-loop rules on tool execution.

    Before any tool execution, the governor verifies:
    1. Tool exists in registry
    2. Tool is permitted by allowlist
    3. Arguments validate against tool schema
    4. Task budget can afford the action
    5. Tool risk class is within safety thresholds
    6. Write actions follow approval policy
    7. Duplicate action fingerprint rule is checked
    8. Retry exemptions are applied
    9. Timeout is configured
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        budget: Budget | None = None,
        tracker: ProgressTracker | None = None,
        sandbox: Sandbox | None = None,
        safety: SafetyRules | None = None,
        write_approval_callback: Callable[[str, Mapping[str, Any]], bool] | None = None,
    ) -> None:
        self.registry = registry
        self.budget = budget
        self.tracker = tracker or ProgressTracker()
        self.sandbox = sandbox or Sandbox(mode="in_process")
        self.safety = safety or SafetyRules()
        self.write_approval_callback = write_approval_callback
        self.events: list[Event] = []
        self.blocked_duplicates_count: int = 0
        self.controller_penalty_total: float = 0.0

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> Event:
        event = Event(type=event_type, message=message, data=data or {})
        self.events.append(event)
        if self.budget is not None:
            self.budget._emit(event_type, message, data)
        return event

    def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        canonical_state: CanonicalState | None = None,
        state_hash_at_call: str | None = None,
        exemptions: RetryExemptions | None = None,
        approved_write: bool = False,
        timeout_seconds: float | None = None,
        record_in_tracker: bool = True,
    ) -> dict[str, Any]:
        """Govern and conditionally execute a tool.

        Returns:
            Dictionary representation of execution outcome or blocking verdict.
        """
        # 1. Verify tool existence
        tool = self.registry.get(tool_name)
        if tool is None:
            msg = f"Tool {tool_name!r} not found in registry."
            self._emit(TOOL_ERROR, msg, {"tool": tool_name})
            return {
                "status": "error",
                "reason": "tool_not_found",
                "message": msg,
            }

        # 2. Check allowlist
        if not self.registry.is_allowed(tool_name, self.safety.allowed_tools):
            msg = f"Tool {tool_name!r} is not allowed by contract safety rules."
            self._emit(TOOL_ERROR, msg, {"tool": tool_name})
            return {
                "status": "blocked",
                "reason": "tool_not_allowed",
                "message": msg,
            }

        # 3. Schema validation
        try:
            valid_args = tool.validate_args(arguments)
        except ToolValidationError as exc:
            self._emit(
                TOOL_VALIDATION_FAILED,
                f"Validation failed for tool {tool_name}: {exc}",
                {"tool": tool_name, "errors": exc.errors},
            )
            return {
                "status": "error",
                "reason": "validation_failed",
                "message": str(exc),
                "errors": exc.errors,
            }

        # 4. Budget affordability check (prospective)
        if self.budget is not None and not self.budget.can_afford(tool_calls=1):
            msg = f"Budget cannot afford tool call for {tool_name!r}."
            self._emit(BUDGET_EXCEEDED, msg, {"tool": tool_name})
            if self.budget.policy.hard_limits:
                self._emit(BUDGET_HARD_LIMIT, msg, {"tool": tool_name})
                return {
                    "status": "blocked",
                    "reason": "budget_exceeded",
                    "message": msg,
                }

        # 5. Risk classification check
        risk_levels = {"read": 0.1, "write": 0.5, "destructive": 1.0, "network": 0.4}
        numeric_risk = risk_levels.get(tool.risk.lower(), 0.5)
        if numeric_risk > self.safety.max_risk:
            msg = (
                f"Tool {tool_name!r} risk {tool.risk!r} ({numeric_risk}) "
                f"exceeds maximum allowed risk ({self.safety.max_risk})."
            )
            self._emit(TOOL_ERROR, msg, {"tool": tool_name, "risk": tool.risk})
            return {
                "status": "blocked",
                "reason": "risk_limit_exceeded",
                "message": msg,
            }

        # 6. Write safety policy
        if (
            tool.risk.lower() in ("write", "destructive")
            and self.safety.require_approval_for_writes
        ):
            has_approval = approved_write or (
                self.write_approval_callback is not None
                and self.write_approval_callback(tool_name, valid_args)
            )
            if not has_approval:
                msg = f"Write action {tool_name!r} requires explicit approval."
                self._emit(TOOL_ERROR, msg, {"tool": tool_name})
                return {
                    "status": "blocked",
                    "reason": "write_approval_required",
                    "message": msg,
                }

        # 7. Action fingerprint computation
        s_hash = state_hash_at_call
        if s_hash is None:
            s_hash = canonical_state.state_hash() if canonical_state is not None else "0" * 64
        fp = action_fingerprint(tool_name, valid_args, s_hash)

        # 8. Retry exemptions evaluation
        effective_exemptions = exemptions or RetryExemptions()
        if tool.idempotent and self.safety.max_risk >= numeric_risk:
            effective_exemptions = effective_exemptions.merged(
                RetryExemptions(idempotent_safe=True)
            )

        # Check duplicate fingerprint rule
        fp_count = self.tracker.fingerprint_count(fp)
        if fp_count >= self.tracker.config.block_threshold:
            if not effective_exemptions.any:
                # Block execution!
                self._emit(
                    TOOL_BLOCKED_DUPLICATE,
                    f"Duplicate tool action blocked: {tool_name} (fingerprint {fp[:12]}...)",
                    {"tool": tool_name, "fingerprint": fp, "count": fp_count},
                )
                block_outcome = self.tracker.register_blocked_duplicate()
                self.blocked_duplicates_count += 1
                self.controller_penalty_total += block_outcome.penalty

                suggested = "escalate" if block_outcome.escalate else "replan"
                return {
                    "status": "blocked",
                    "reason": "duplicate_action",
                    "message": (
                        "This exact action fingerprint was already attempted. "
                        "Change arguments, tool, or strategy."
                    ),
                    "suggested_next_action": suggested,
                    "escalate": block_outcome.escalate,
                    "blocked_count": block_outcome.blocked_count,
                }
            else:
                self._emit(
                    RETRY_EXEMPTED,
                    f"Retry granted exemption for {tool_name}: {effective_exemptions.active}",
                    {"tool": tool_name, "exemptions": effective_exemptions.active},
                )

        if fp_count > 0:
            self._emit(
                RETRY, f"Retrying action {tool_name}", {"tool": tool_name, "count": fp_count}
            )

        # 9. Configure timeout and execute
        effective_timeout = timeout_seconds if timeout_seconds is not None else tool.timeout_seconds

        # Charge budget ONLY on execution attempt (not when blocked)
        if self.budget is not None:
            self.budget.record_tool_call(retried=(fp_count > 0))

        # Execute in sandbox
        sandbox_result = self.sandbox.run(
            tool.callable,
            **valid_args,
            timeout_seconds=effective_timeout,
        )

        # Handle outcome and record in tracker
        res_dump = sandbox_result.model_dump()
        res_dump["fingerprint"] = fp

        if sandbox_result.timed_out:
            self._emit(
                TOOL_TIMEOUT,
                f"Tool {tool_name} timed out after {effective_timeout}s",
                {"tool": tool_name, "timeout": effective_timeout},
            )
            return res_dump

        if sandbox_result.status == "error":
            self._emit(
                TOOL_ERROR,
                f"Tool {tool_name} failed: {sandbox_result.error}",
                {"tool": tool_name, "error": sandbox_result.error},
            )
            # Record failed step in tracker so future attempts know the history
            if record_in_tracker:
                self.tracker.score_step(
                    tool_name=tool_name,
                    arguments=valid_args,
                    output=str(sandbox_result.error),
                    fingerprint=fp,
                    state_hash_before=s_hash,
                    state_hash_after=s_hash,
                    milestones_before=0,
                    milestones_after=0,
                    exemptions=effective_exemptions,
                    is_error=True,
                )
            return res_dump

        # Success
        self._emit(
            TOOL_SUCCESS,
            f"Tool {tool_name} succeeded",
            {"tool": tool_name, "duration_ms": sandbox_result.duration_ms},
        )
        if record_in_tracker:
            self.tracker.score_step(
                tool_name=tool_name,
                arguments=valid_args,
                output=str(sandbox_result.result),
                fingerprint=fp,
                state_hash_before=s_hash,
                state_hash_after=s_hash,
                milestones_before=0,
                milestones_after=0,
                exemptions=effective_exemptions,
                is_error=False,
            )
        return res_dump
