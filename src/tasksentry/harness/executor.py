"""Task step executor measuring latency, costs, state hashing, and APG scoring."""

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.budget.budget import Budget
from tasksentry.core.state import CanonicalState
from tasksentry.harness.verification import VerificationResult
from tasksentry.math.progress import ProgressTracker, RetryExemptions
from tasksentry.tools.governor import ToolGovernor


class StepResult(BaseModel):
    """Structured execution outcome of a single task step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: dict[str, Any]
    observation: str
    status: str
    duration_ms: float
    tokens: int
    cost_usd: float
    state_hash_before: str
    state_hash_after: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    apg: float
    window_gain: float
    ema: float
    decision: str
    stdout: str = ""
    stderr: str = ""


class Executor:
    """Dispatches governed actions through the sandbox, tracking costs, latency, and progress."""

    def __init__(
        self,
        governor: ToolGovernor,
        tracker: ProgressTracker,
        budget: Budget | None = None,
    ) -> None:
        self.governor = governor
        self.tracker = tracker
        self.budget = budget

    def execute_step(
        self,
        action: dict[str, Any],
        canonical_state: CanonicalState,
        *,
        context: dict[str, Any] | None = None,
        exemptions: RetryExemptions | None = None,
        approved_write: bool = False,
        verification_results: list[VerificationResult] | None = None,
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> tuple[StepResult, CanonicalState]:
        """Execute one governed step, update canonical state, and score APG."""
        tool_name = action.get("tool") or action.get("name") or "unknown_tool"
        arguments = action.get("arguments", {})

        state_before_hash = canonical_state.state_hash()
        step_events: list[dict[str, Any]] = []

        # Record tokens and cost on budget if provided
        if self.budget is not None and (tokens > 0 or cost_usd > 0.0):
            self.budget.record_usage(input_tokens=tokens, cost_usd=cost_usd)

        t_start = time.perf_counter()

        # Delegate execution to ToolGovernor
        gov_res = self.governor.execute(
            tool_name,
            arguments,
            canonical_state=canonical_state,
            state_hash_at_call=state_before_hash,
            exemptions=exemptions,
            approved_write=approved_write,
        )

        duration_ms = (time.perf_counter() - t_start) * 1000.0

        status = gov_res.get("status", "error")
        stdout = gov_res.get("stdout", "")
        stderr = gov_res.get("stderr", "")

        # Format observation
        if status == "success":
            observation = str(gov_res.get("result", ""))
        elif status == "blocked":
            observation = f"Blocked: {gov_res.get('message', 'action blocked')}"
        elif status == "timeout":
            observation = f"Timeout: {gov_res.get('error', 'action timed out')}"
        else:
            observation = (
                f"Error: {gov_res.get('message') or gov_res.get('error') or 'action failed'}"
            )

        # Determine new canonical state
        new_state = canonical_state
        if status == "success":
            # Update world with any reported facts or artifacts
            if context and "new_facts" in context:
                for k, v in context["new_facts"].items():
                    new_state = new_state.with_fact(k, v)
            if context and "new_world" in context:
                new_state = new_state.with_world(**context["new_world"])

        state_after_hash = new_state.state_hash()

        # Collect events emitted during this step
        step_events = [e.model_dump() for e in self.governor.events[-3:]]

        # Serialized verifications
        verif_data = [r.model_dump() for r in (verification_results or [])]

        # APG and loop decision calculation
        if status == "blocked":
            # Blocked duplicates DO NOT enter WindowGain and carry separate controller penalty
            wg = self.tracker.window_gain()
            ema_val = self.tracker.ema
            dec = gov_res.get("suggested_next_action", "replan")
            step_result = StepResult(
                action=action,
                observation=observation,
                status=status,
                duration_ms=duration_ms,
                tokens=tokens,
                cost_usd=cost_usd,
                state_hash_before=state_before_hash,
                state_hash_after=state_after_hash,
                events=step_events,
                verification_results=verif_data,
                apg=0.0,
                window_gain=wg,
                ema=ema_val,
                decision=dec,
                stdout=stdout,
                stderr=stderr,
            )
            return step_result, new_state

        # Score executed step
        score = self.tracker.score_step(
            tool_name=tool_name,
            arguments=arguments,
            output=observation,
            fingerprint=gov_res.get("fingerprint", state_before_hash),
            state_hash_before=state_before_hash,
            state_hash_after=state_after_hash,
            milestones_before=canonical_state.milestone_count,
            milestones_after=new_state.milestone_count,
            cost_usd=cost_usd,
            exemptions=exemptions,
            is_error=(status != "success"),
            is_transient_failure=(status == "timeout"),
        )

        step_result = StepResult(
            action=action,
            observation=observation,
            status=status,
            duration_ms=duration_ms,
            tokens=tokens,
            cost_usd=cost_usd,
            state_hash_before=state_before_hash,
            state_hash_after=state_after_hash,
            events=step_events,
            verification_results=verif_data,
            apg=score.apg,
            window_gain=score.window_gain,
            ema=score.ema,
            decision=score.verdict.action.value,
            stdout=stdout,
            stderr=stderr,
        )
        return step_result, new_state
