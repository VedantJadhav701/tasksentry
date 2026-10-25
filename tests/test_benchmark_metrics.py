"""Unit tests for benchmark metrics calculation."""

from tasksentry.benchmark.metrics import BenchmarkMetrics, calculate_metrics


def test_metrics_empty() -> None:
    m = calculate_metrics([])
    assert isinstance(m, BenchmarkMetrics)
    assert m.total_tasks == 0
    assert m.task_success_rate == 0.0


def test_metrics_calculation() -> None:
    records = [
        {
            "success": True,
            "cost_usd": 0.02,
            "tokens": 400,
            "input_tokens": 300,
            "output_tokens": 100,
            "tool_calls": 3,
            "executed_actions": 3,
            "wasted_actions": 0,
            "wall_time_seconds": 1.2,
            "budget_exceeded": False,
            "loop_warnings": 0,
            "duplicate_calls_blocked": 0,
        },
        {
            "success": True,
            "cost_usd": 0.03,
            "tokens": 600,
            "input_tokens": 450,
            "output_tokens": 150,
            "tool_calls": 5,
            "executed_actions": 5,
            "wasted_actions": 1,
            "wall_time_seconds": 2.0,
            "budget_exceeded": False,
            "loop_warnings": 1,
            "duplicate_calls_blocked": 1,
        },
        {
            "success": False,
            "cost_usd": 0.01,
            "tokens": 200,
            "input_tokens": 150,
            "output_tokens": 50,
            "tool_calls": 2,
            "executed_actions": 2,
            "wasted_actions": 2,
            "wall_time_seconds": 0.8,
            "budget_exceeded": True,
            "loop_warnings": 0,
            "duplicate_calls_blocked": 0,
        },
    ]

    m = calculate_metrics(records, total_cost_budget=1.0)
    assert m.total_tasks == 3
    assert m.successful_tasks == 2
    assert m.task_success_rate == 0.6667
    assert m.cost_per_successful_task == 0.025
    assert m.tokens_per_successful_task == 500.0
    assert m.tool_calls_per_task == 3.33
    assert m.wasted_action_rate == 0.3
    assert m.budget_compliance_rate == 0.6667
    assert m.p50_latency > 0.0
    assert m.p95_latency >= m.p50_latency
    assert m.efficiency_adjusted_success_rate > 0.0
