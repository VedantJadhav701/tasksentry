"""Unit tests for the TaskSentry Budget system."""

import time

import pytest

from tasksentry.budget.budget import Budget
from tasksentry.budget.policy import BudgetPolicy
from tasksentry.core.events import BUDGET_EXCEEDED, BUDGET_HARD_LIMIT, BUDGET_WARNING
from tasksentry.exceptions import BudgetExceededError


def test_budget_initial_state() -> None:
    budget = Budget(max_tokens=1000, max_cost_usd=5.0, max_llm_calls=10, max_tool_calls=20)
    assert budget.total_tokens == 0
    assert budget.cost_usd == 0.0
    assert budget.llm_calls == 0
    assert budget.tool_calls == 0
    assert budget.retries == 0

    rem = budget.remaining_budget()
    assert rem["remaining_tokens"] == 1000
    assert rem["remaining_cost_usd"] == 5.0
    assert rem["remaining_llm_calls"] == 10
    assert rem["remaining_tool_calls"] == 20


def test_token_accounting() -> None:
    budget = Budget(max_tokens=100)
    budget.record_usage(input_tokens=30, output_tokens=20)
    assert budget.input_tokens == 30
    assert budget.output_tokens == 20
    assert budget.total_tokens == 50
    assert budget.remaining_budget()["remaining_tokens"] == 50


def test_cost_accounting() -> None:
    budget = Budget(max_cost_usd=1.0)
    budget.record_usage(cost_usd=0.25)
    budget.record_usage(cost_usd=0.15)
    assert round(budget.cost_usd, 6) == 0.40
    summary = budget.usage_summary()
    assert summary["cost_usd"] == 0.40


def test_call_counting() -> None:
    budget = Budget(max_llm_calls=5, max_tool_calls=5)
    budget.record_usage(llm_calls=2)
    budget.record_tool_call(count=1, retried=False)
    budget.record_tool_call(count=1, retried=True)

    assert budget.llm_calls == 2
    assert budget.tool_calls == 2
    assert budget.retries == 1


def test_warning_at_80_percent() -> None:
    budget = Budget(max_tokens=100)
    # Consuming 79 tokens should not trigger warning
    budget.record_usage(input_tokens=79)
    assert not any(e.type == BUDGET_WARNING for e in budget.events)

    # Consuming 1 more reaches 80%
    budget.record_usage(input_tokens=1)
    warnings = [e for e in budget.events if e.type == BUDGET_WARNING]
    assert len(warnings) == 1
    assert warnings[0].data["dimension"] == "tokens"
    assert warnings[0].data["ratio"] == 0.80

    # Consuming up to 90% should not re-emit warning for same dimension
    budget.record_usage(input_tokens=10)
    assert len([e for e in budget.events if e.type == BUDGET_WARNING]) == 1


def test_hard_limit_budget_exceeded_error() -> None:
    budget = Budget(max_tokens=100)
    budget.record_usage(input_tokens=70)

    # Attempting to exceed hard limit raises BudgetExceededError
    with pytest.raises(BudgetExceededError):
        budget.record_usage(input_tokens=35)

    assert any(e.type == BUDGET_EXCEEDED for e in budget.events)
    assert any(e.type == BUDGET_HARD_LIMIT for e in budget.events)


def test_record_usage_records_before_raising() -> None:
    budget = Budget(max_tokens=50)
    # Exceeding budget must still record the attempted/consumed usage
    with pytest.raises(BudgetExceededError):
        budget.record_usage(input_tokens=60)

    assert budget.total_tokens == 60
    assert budget.input_tokens == 60


def test_soft_limit_overflow_allowed() -> None:
    policy = BudgetPolicy(hard_limits=False)
    budget = Budget(max_tokens=100, policy=policy)
    # With soft limits, record_usage logs BUDGET_EXCEEDED but does not raise
    budget.record_usage(input_tokens=120)
    assert budget.total_tokens == 120
    assert any(e.type == BUDGET_EXCEEDED for e in budget.events)
    assert not any(e.type == BUDGET_HARD_LIMIT for e in budget.events)


def test_can_afford_and_check() -> None:
    budget = Budget(max_tokens=100, max_cost_usd=2.0)
    assert budget.can_afford(tokens=50, cost_usd=1.0)
    assert not budget.can_afford(tokens=101)
    assert not budget.can_afford(cost_usd=2.5)

    # check() raises if hard limit would be violated
    with pytest.raises(BudgetExceededError):
        budget.check(tokens=150)


def test_wall_time_limit() -> None:
    # Set a tiny wall time
    budget = Budget(max_wall_time_seconds=0.05)
    time.sleep(0.06)
    with pytest.raises(BudgetExceededError):
        budget.check()


def test_negative_accounting_rejected() -> None:
    budget = Budget()
    with pytest.raises(ValueError):
        budget.record_usage(input_tokens=-1)
    with pytest.raises(ValueError):
        budget.record_usage(cost_usd=-0.5)
