"""Unit tests for the budget() context manager wrapper and ambient contextvars."""

import pytest

from tasksentry.budget.budget import BudgetContext, budget, get_current_budget
from tasksentry.exceptions import BudgetExceededError


def test_budget_wrapper_usage_recording() -> None:
    with budget(
        task_id="test-run",
        max_tokens=10_000,
        max_cost_usd=1.0,
    ) as ctx:
        assert get_current_budget() is ctx
        ctx.record_usage(input_tokens=100, output_tokens=50, cost_usd=0.01)

        rem = ctx.remaining_budget()
        assert rem["remaining_tokens"] == 9850
        assert rem["remaining_cost_usd"] == 0.99

        rec = ctx.receipt()
        assert rec.task_id == "test-run"
        assert rec.tokens == 150
        assert rec.cost_usd == 0.01

    # Ambient context is cleared on exit
    assert get_current_budget() is None


def test_budget_wrapper_tool_call_recording() -> None:
    with budget(
        task_id="tool-run",
        max_tool_calls=5,
    ) as ctx:
        ctx.record_tool_call(tool="search", cost_usd=0.02, latency_ms=120.0)
        ctx.record_tool_call(tool="fetch", cost_usd=0.01, latency_ms=80.0)

        rem = ctx.remaining_budget()
        assert rem["remaining_tool_calls"] == 3
        assert ctx.budget.tool_calls == 2
        assert round(ctx.budget.cost_usd, 2) == 0.03


def test_budget_wrapper_hard_limit_raises_exceeded_error() -> None:
    with pytest.raises(BudgetExceededError), budget(
        task_id="limit-test",
        max_tool_calls=2,
        on_exceed="raise",
    ) as ctx:
        ctx.record_tool_call(tool="call1")
        ctx.record_tool_call(tool="call2")


def test_budget_wrapper_summarize_and_stop_callback() -> None:
    stopped_contexts: list[BudgetContext] = []

    def on_stop(c: BudgetContext) -> None:
        stopped_contexts.append(c)

    with budget(
        task_id="stop-test",
        max_tool_calls=2,
        on_exceed="summarize_and_stop",
        stop_callback=on_stop,
    ) as ctx:
        ctx.record_tool_call(tool="call1")
        ctx.record_tool_call(tool="call2")

        # Did not raise, marked stopped
        assert ctx.stopped is True
        assert len(stopped_contexts) == 1
        assert stopped_contexts[0] is ctx

        rec = ctx.receipt()
        assert rec.status == "stopped"


def test_budget_wrapper_nested_contexts() -> None:
    with budget(task_id="outer", max_tokens=1000) as outer_ctx:
        assert get_current_budget() is outer_ctx
        outer_ctx.record_usage(input_tokens=100, output_tokens=50)

        with budget(task_id="inner", max_tokens=200) as inner_ctx:
            assert get_current_budget() is inner_ctx
            inner_ctx.record_usage(input_tokens=20, output_tokens=10)
            assert inner_ctx.budget.total_tokens == 30
            assert outer_ctx.budget.total_tokens == 150

        # After inner exits, outer is restored
        assert get_current_budget() is outer_ctx
        assert outer_ctx.budget.total_tokens == 150

    assert get_current_budget() is None
