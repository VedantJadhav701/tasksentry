"""Task stop conditions, budget limits, loop detection, and termination evaluation."""

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.budget.budget import Budget
from tasksentry.math.progress import LoopAction, evaluate_loop_policy


class StopConditionVerdict(BaseModel):
    """The aggregate controller verdict on whether to stop, warn, replan, or continue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: LoopAction
    reason: str
    should_stop: bool
    details: dict[str, Any] = Field(default_factory=dict)


def evaluate_stop_conditions(
    *,
    window_gain: float,
    history_len: int,
    window: int = 5,
    budget: Budget | None = None,
    all_criteria_passed: bool = False,
    blocked_duplicates_count: int = 0,
    unsafe_action_repeated: bool = False,
) -> StopConditionVerdict:
    """Evaluate canonical progress policy and termination gates.

    Evaluates:
    1. Success: All objective verification criteria passed -> Stop (Completed)
    2. Blocked duplicates: >= 3 blocked calls -> Stop (Escalated)
    3. Safety violations: repeated unsafe actions -> Stop
    4. Budget: hard limits or wall time exceeded -> Stop (Budget Exhausted)
    5. Mathematical loop policy (Phase 1 canonical thresholds)
    """
    # 1. Verification success check
    if all_criteria_passed:
        return StopConditionVerdict(
            action=LoopAction.CONTINUE,
            reason="all_verification_gates_passed",
            should_stop=True,
            details={"success": True},
        )

    # 2. Duplicate escalation rule
    if blocked_duplicates_count >= 3:
        return StopConditionVerdict(
            action=LoopAction.STOP,
            reason="three_blocked_duplicates",
            should_stop=True,
            details={"blocked_count": blocked_duplicates_count},
        )

    # 3. Repeated unsafe action
    if unsafe_action_repeated:
        return StopConditionVerdict(
            action=LoopAction.STOP,
            reason="repeated_unsafe_action",
            should_stop=True,
            details={"unsafe": True},
        )

    # 4. Budget limit checks
    if budget is not None:
        if budget.max_tool_calls is not None and budget.tool_calls >= budget.max_tool_calls:
            return StopConditionVerdict(
                action=LoopAction.STOP,
                reason="max_tool_calls_reached",
                should_stop=True,
                details={"tool_calls": budget.tool_calls, "limit": budget.max_tool_calls},
            )

        if budget.max_llm_calls is not None and budget.llm_calls >= budget.max_llm_calls:
            return StopConditionVerdict(
                action=LoopAction.STOP,
                reason="max_llm_calls_reached",
                should_stop=True,
                details={"llm_calls": budget.llm_calls, "limit": budget.max_llm_calls},
            )

        if budget.max_tokens is not None and budget.total_tokens >= budget.max_tokens:
            return StopConditionVerdict(
                action=LoopAction.STOP,
                reason="max_tokens_reached",
                should_stop=True,
                details={"total_tokens": budget.total_tokens, "limit": budget.max_tokens},
            )

        if budget.max_cost_usd is not None and budget.cost_usd >= budget.max_cost_usd:
            return StopConditionVerdict(
                action=LoopAction.STOP,
                reason="max_cost_usd_reached",
                should_stop=True,
                details={"cost_usd": budget.cost_usd, "limit": budget.max_cost_usd},
            )

        if (
            budget.max_wall_time_seconds is not None
            and budget.wall_time_seconds >= budget.max_wall_time_seconds
        ):
            return StopConditionVerdict(
                action=LoopAction.STOP,
                reason="max_wall_time_reached",
                should_stop=True,
                details={
                    "wall_time_seconds": budget.wall_time_seconds,
                    "limit": budget.max_wall_time_seconds,
                },
            )

        if budget.expires_at is not None and time.time() > budget.expires_at:
            return StopConditionVerdict(
                action=LoopAction.STOP,
                reason="budget_expired",
                should_stop=True,
                details={"expires_at": budget.expires_at},
            )

    # 5. Canonical Phase 1 loop policy evaluation
    verdict = evaluate_loop_policy(window_gain, history_len, window)
    if verdict.action == LoopAction.STOP:
        return StopConditionVerdict(
            action=LoopAction.STOP,
            reason=verdict.reason,
            should_stop=True,
            details={"window_gain": window_gain, "history_len": history_len},
        )

    if verdict.action == LoopAction.REPLAN:
        return StopConditionVerdict(
            action=LoopAction.REPLAN,
            reason=verdict.reason,
            should_stop=False,
            details={"window_gain": window_gain, "history_len": history_len},
        )

    if verdict.action == LoopAction.WARN:
        return StopConditionVerdict(
            action=LoopAction.WARN,
            reason=verdict.reason,
            should_stop=False,
            details={"window_gain": window_gain, "history_len": history_len},
        )

    return StopConditionVerdict(
        action=LoopAction.CONTINUE,
        reason=verdict.reason,
        should_stop=False,
        details={"window_gain": window_gain, "history_len": history_len},
    )
