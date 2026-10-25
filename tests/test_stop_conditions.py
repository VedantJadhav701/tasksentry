"""Unit tests for task stop conditions and mathematical loop thresholds."""

from tasksentry.budget.budget import Budget
from tasksentry.harness.stop_conditions import evaluate_stop_conditions
from tasksentry.math.progress import LoopAction


def test_cold_start() -> None:
    # History length 3 < window 5 -> cold_start continue
    res = evaluate_stop_conditions(window_gain=-1.5, history_len=3, window=5)
    assert res.should_stop is False
    assert res.action == LoopAction.CONTINUE
    assert res.reason == "cold_start"


def test_positive_gain() -> None:
    res = evaluate_stop_conditions(window_gain=1.2, history_len=5, window=5)
    assert res.should_stop is False
    assert res.action == LoopAction.CONTINUE
    assert res.reason == "window_gain_positive"


def test_zero_gain_warns() -> None:
    res = evaluate_stop_conditions(window_gain=0.0, history_len=5, window=5)
    assert res.should_stop is False
    assert res.action == LoopAction.WARN
    assert res.reason == "window_gain_zero"


def test_slightly_negative_gain_warns() -> None:
    res = evaluate_stop_conditions(window_gain=-0.5, history_len=5, window=5)
    assert res.should_stop is False
    assert res.action == LoopAction.WARN
    assert res.reason == "window_gain_slightly_negative"


def test_force_replan_threshold() -> None:
    res = evaluate_stop_conditions(window_gain=-1.2, history_len=5, window=5)
    assert res.should_stop is False
    assert res.action == LoopAction.REPLAN
    assert res.reason == "window_gain_requires_replan"


def test_stop_threshold() -> None:
    res = evaluate_stop_conditions(window_gain=-2.0, history_len=5, window=5)
    assert res.should_stop is True
    assert res.action == LoopAction.STOP
    assert res.reason == "window_gain_at_stop_threshold"


def test_verification_success_stops() -> None:
    res = evaluate_stop_conditions(
        window_gain=-5.0,  # Even with negative gain, verified completion stops as success!
        history_len=10,
        all_criteria_passed=True,
    )
    assert res.should_stop is True
    assert res.reason == "all_verification_gates_passed"
    assert res.details["success"] is True


def test_three_blocked_duplicates_stops() -> None:
    res = evaluate_stop_conditions(
        window_gain=2.0,
        history_len=10,
        blocked_duplicates_count=3,
    )
    assert res.should_stop is True
    assert res.action == LoopAction.STOP
    assert res.reason == "three_blocked_duplicates"


def test_budget_exhaustion_stops() -> None:
    budget = Budget(max_tool_calls=2)
    budget.record_tool_call()
    budget.record_tool_call()

    res = evaluate_stop_conditions(
        window_gain=1.0,
        history_len=10,
        budget=budget,
    )
    assert res.should_stop is True
    assert res.reason == "max_tool_calls_reached"
