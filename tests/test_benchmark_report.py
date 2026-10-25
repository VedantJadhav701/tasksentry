"""Unit tests for benchmark Markdown report generation."""

from tasksentry.benchmark.report import generate_markdown_report


def test_markdown_report_formatting() -> None:
    data = {
        "metadata": {
            "timestamp": "2026-10-25T12:00:00Z",
            "suite": "offline-v0.1",
            "seed": 42,
            "python_version": "3.11.0",
            "tasksentry_version": "0.1.0",
            "routine_model": "llama3.2:1b",
            "reasoning_model": "qwen3:4b-instruct-2507-q4_K_M",
        },
        "aggregates": {
            "react_baseline": {
                "task_success_rate": 0.45,
                "pass_at_3": 0.65,
                "tokens_per_successful_task": 520.0,
                "tool_calls_per_task": 4.1,
                "p95_latency": 0.12,
                "budget_compliance_rate": 0.70,
            },
            "tasksentry_case": {
                "task_success_rate": 0.95,
                "pass_at_3": 1.0,
                "tokens_per_successful_task": 310.0,
                "tool_calls_per_task": 3.0,
                "p95_latency": 0.08,
                "budget_compliance_rate": 1.0,
            },
        },
        "case_ablations": {
            "tasksentry_case": {
                "task_success_rate": 0.95,
                "tokens_per_successful_task": 310.0,
                "p95_latency": 0.08,
                "budget_compliance_rate": 1.0,
            },
            "case_ablation_no_apg": {
                "task_success_rate": 0.70,
                "tokens_per_successful_task": 480.0,
                "p95_latency": 0.15,
                "budget_compliance_rate": 0.75,
            },
        },
        "per_task_results": [{"task_id": "t1"}],
    }

    md = generate_markdown_report(data)
    assert "# TaskSentryBench v0.1" in md
    assert "## Run metadata" in md
    assert "2026-10-25T12:00:00Z" in md
    assert "## Aggregate results" in md
    assert "| `tasksentry_case` |" in md
    assert "## CASE ablations" in md
    assert "| `case_ablation_no_apg` |" in md
    assert "## Interpretation" in md
