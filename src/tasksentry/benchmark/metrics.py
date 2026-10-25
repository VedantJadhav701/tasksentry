"""Benchmark metrics evaluation and aggregation.

NOTE: These metrics are benchmark measurements computed under controlled, synthetic
or local conditions for regression detection and fair system comparisons. They are
not guarantees of production reliability, safety, or latency under real workloads.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkMetrics(BaseModel):
    """Aggregate evaluation metrics for a benchmark run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_tasks: int = 0
    successful_tasks: int = 0
    task_success_rate: float = 0.0
    pass_at_1: float = 0.0
    pass_at_3: float = 0.0
    cost_per_successful_task: float = 0.0
    tokens_per_successful_task: float = 0.0
    input_tokens_per_task: float = 0.0
    output_tokens_per_task: float = 0.0
    tool_calls_per_task: float = 0.0
    duplicate_tool_calls: int = 0
    wasted_action_rate: float = 0.0
    loop_escape_rate: float = 0.0
    p50_latency: float = 0.0
    p95_latency: float = 0.0
    budget_compliance_rate: float = 0.0
    safety_violation_rate: float = 0.0
    escalation_rate: float = 0.0
    verification_pass_rate: float = 0.0
    efficiency_adjusted_success_rate: float = 0.0
    extra: dict[str, Any] = Field(default_factory=dict)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    d = k - f
    return round(sorted_v[f] + d * (sorted_v[c] - sorted_v[f]), 4)


def calculate_metrics(
    task_results: list[dict[str, Any]],
    total_cost_budget: float = 100.0,
) -> BenchmarkMetrics:
    """Compute aggregate benchmark metrics from a sequence of raw task execution results.

    Args:
        task_results: list of dictionaries capturing per-task run telemetry.
        total_cost_budget: overall benchmark cost budget used for efficiency adjustment.

    Returns:
        BenchmarkMetrics containing all required benchmark formulas.
    """
    total = len(task_results)
    if total == 0:
        return BenchmarkMetrics()

    successes = [r for r in task_results if r.get("success", False)]
    success_count = len(successes)
    success_rate = round(success_count / total, 4)

    # Cost per successful task
    total_success_cost = sum(float(r.get("cost_usd", 0.0)) for r in successes)
    cost_per_succ = round(total_success_cost / success_count, 6) if success_count > 0 else 0.0

    # Tokens per successful task
    total_success_tokens = sum(int(r.get("tokens", 0)) for r in successes)
    tokens_per_succ = round(total_success_tokens / success_count, 2) if success_count > 0 else 0.0

    total_in_tokens = sum(int(r.get("input_tokens", 0)) for r in task_results)
    total_out_tokens = sum(int(r.get("output_tokens", 0)) for r in task_results)
    in_per_task = round(total_in_tokens / total, 2)
    out_per_task = round(total_out_tokens / total, 2)

    total_tool_calls = sum(int(r.get("tool_calls", 0)) for r in task_results)
    tool_calls_per_task = round(total_tool_calls / total, 2)

    duplicate_calls = sum(
        int(r.get("duplicate_calls_blocked", 0) + r.get("duplicate_tool_calls", 0))
        for r in task_results
    )

    # Wasted actions rate: actions with APG <= 0 / total executed actions
    total_executed_actions = sum(
        int(r.get("executed_actions", r.get("tool_calls", 0))) for r in task_results
    )
    wasted_actions = sum(int(r.get("wasted_actions", 0)) for r in task_results)
    wasted_rate = (
        round(wasted_actions / total_executed_actions, 4) if total_executed_actions > 0 else 0.0
    )

    # Loop escape rate: recovered / entering low-gain
    low_gain_tasks = sum(
        1 for r in task_results if r.get("entered_low_gain", False) or r.get("loop_warnings", 0) > 0
    )
    recovered_tasks = sum(
        1
        for r in task_results
        if (r.get("entered_low_gain", False) or r.get("loop_warnings", 0) > 0)
        and r.get("success", False)
    )
    escape_rate = round(recovered_tasks / low_gain_tasks, 4) if low_gain_tasks > 0 else 1.0

    # Latency percentiles
    latencies = [float(r.get("wall_time_seconds", 0.0)) for r in task_results]
    p50_lat = _percentile(latencies, 50.0)
    p95_lat = _percentile(latencies, 95.0)

    # Budget compliance
    within_budget = sum(1 for r in task_results if not r.get("budget_exceeded", False))
    budget_compliance = round(within_budget / total, 4)

    # Safety violations
    safety_violations = sum(1 for r in task_results if r.get("safety_violation", False))
    safety_rate = round(safety_violations / total, 4)

    # Escalations
    escalations = sum(1 for r in task_results if r.get("status") == "escalated")
    escalation_rate = round(escalations / total, 4)

    # Verification pass rate
    total_checks = sum(int(r.get("total_verifications", 1)) for r in task_results)
    passed_checks = sum(
        int(r.get("passed_verifications", 1 if r.get("success") else 0)) for r in task_results
    )
    verification_rate = round(passed_checks / total_checks, 4) if total_checks > 0 else 0.0

    # Efficiency-adjusted success rate
    total_cost_used = sum(float(r.get("cost_usd", 0.0)) for r in task_results)
    cost_fraction = min(1.0, max(0.0, total_cost_used / max(1e-6, total_cost_budget)))
    eff_adjusted = round(success_rate * (1.0 - cost_fraction), 4)

    # Pass@1 and Pass@3
    # If tasks are grouped or have attempts
    pass_at_1 = success_rate
    # Pass@3: probability of at least one success in 3 attempts = 1 - (1 - p)^3
    pass_at_3 = round(1.0 - (1.0 - success_rate) ** 3, 4)

    return BenchmarkMetrics(
        total_tasks=total,
        successful_tasks=success_count,
        task_success_rate=success_rate,
        pass_at_1=pass_at_1,
        pass_at_3=pass_at_3,
        cost_per_successful_task=cost_per_succ,
        tokens_per_successful_task=tokens_per_succ,
        input_tokens_per_task=in_per_task,
        output_tokens_per_task=out_per_task,
        tool_calls_per_task=tool_calls_per_task,
        duplicate_tool_calls=duplicate_calls,
        wasted_action_rate=wasted_rate,
        loop_escape_rate=escape_rate,
        p50_latency=p50_lat,
        p95_latency=p95_lat,
        budget_compliance_rate=budget_compliance,
        safety_violation_rate=safety_rate,
        escalation_rate=escalation_rate,
        verification_pass_rate=verification_rate,
        efficiency_adjusted_success_rate=eff_adjusted,
    )
