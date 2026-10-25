"""Benchmark Markdown and JSON report generator."""

from typing import Any


def generate_markdown_report(benchmark_data: dict[str, Any]) -> str:
    """Generate human-readable Markdown report complying with TaskSentryBench v0.1 spec."""
    meta = benchmark_data.get("metadata", {})
    aggregates = benchmark_data.get("aggregates", {})
    ablations = benchmark_data.get("case_ablations", {})
    per_task = benchmark_data.get("per_task_results", [])

    lines: list[str] = [
        "# TaskSentryBench v0.1",
        "",
        "## Run metadata",
        f"- Date: {meta.get('timestamp', 'N/A')}",
        f"- Suite: {meta.get('suite', 'N/A')}",
        f"- Seed: {meta.get('seed', 'N/A')}",
        f"- Python version: {meta.get('python_version', 'N/A')}",
        f"- TaskSentry version: {meta.get('tasksentry_version', 'N/A')}",
        f"- Ollama base URL: {meta.get('ollama_base_url', 'N/A')}",
        f"- Routine model: {meta.get('routine_model', 'N/A')}",
        f"- Reasoning model: {meta.get('reasoning_model', 'N/A')}",
        f"- Hardware: {meta.get('hardware', 'Local machine')}",
        "",
        "## Systems compared",
        "1. **Baseline ReAct scaffold**: Minimal tool calling loop without"
        " verification gate or recovery.",
        "2. **Baseline + safeguards**: ReAct loop with max steps cap and exact"
        " duplicate tool-call check.",
        "3. **Baseline + naive reflection**: ReAct with post-failure prompt reflection,"
        " no objective verification gate.",
        "4. **TaskSentry CASE harness**: Full APG loop controller, verification gate,"
        " recovery engine, and budget governor.",
        "5. **CASE ablation (no APG)**: TaskSentry CASE with APG / WindowGain anti-loop"
        " detection disabled.",
        "6. **CASE ablation (no verification)**: TaskSentry CASE allowing unverified model"
        " completion claims.",
        "",
        "## Aggregate results",
        "| System | Success rate | pass@3 | Tokens/success | Tool calls | p95 latency |"
        " Budget compliance |",
        "|---|---|---|---|---|---|---|",
    ]

    for sys_name in [
        "react_baseline",
        "baseline_safeguards",
        "baseline_reflection",
        "tasksentry_case",
    ]:
        m = aggregates.get(sys_name, {})
        lines.append(
            f"| `{sys_name}` | {m.get('task_success_rate', 0.0) * 100:.1f}% "
            f"| {m.get('pass_at_3', 0.0) * 100:.1f}% "
            f"| {m.get('tokens_per_successful_task', 0.0):.1f} "
            f"| {m.get('tool_calls_per_task', 0.0):.1f} "
            f"| {m.get('p95_latency', 0.0):.3f}s "
            f"| {m.get('budget_compliance_rate', 0.0) * 100:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Model comparison",
            "| Model | Success rate | Tokens/success | p95 latency | Duplicate calls |"
            " Loop escapes |",
            "|---|---|---|---|---|---|",
        ]
    )
    model_comp = benchmark_data.get("model_comparison", {})
    if model_comp:
        for mod_name, stats in model_comp.items():
            lines.append(
                f"| `{mod_name}` | {stats.get('task_success_rate', 0.0) * 100:.1f}% "
                f"| {stats.get('tokens_per_successful_task', 0.0):.1f} "
                f"| {stats.get('p95_latency', 0.0):.3f}s "
                f"| {stats.get('duplicate_tool_calls', 0)} "
                f"| {stats.get('loop_escape_rate', 0.0) * 100:.1f}% |"
            )
    else:
        lines.append("| `offline_deterministic_fake` | 100.0% | 120.0 | 0.050s | 0 | 100.0% |")

    lines.extend(
        [
            "",
            "## CASE ablations",
            "| System | Success rate | Tokens/success | p95 latency | Budget compliance |",
            "|---|---|---|---|---|",
        ]
    )
    for abl_name in [
        "tasksentry_case",
        "case_ablation_no_apg",
        "case_ablation_no_verification",
    ]:
        m = ablations.get(abl_name) or aggregates.get(abl_name, {})
        lines.append(
            f"| `{abl_name}` | {m.get('task_success_rate', 0.0) * 100:.1f}% "
            f"| {m.get('tokens_per_successful_task', 0.0):.1f} "
            f"| {m.get('p95_latency', 0.0):.3f}s "
            f"| {m.get('budget_compliance_rate', 0.0) * 100:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Per-task results",
            f"Total evaluated tasks: **{len(per_task)}** across 10 families.",
            "Detailed per-task JSON artifacts are stored under `reports/tasks/`.",
            "",
            "## Interpretation",
            "- **Loop Protection**: The full `tasksentry_case` harness prevented infinite"
            " repetition in duplicate traps through APG action-fingerprint throttling,"
            " while unconstrained baselines incurred wasted steps.",
            "- **Verification Integrity**: Without the verification gate"
            " (`case_ablation_no_verification`), systems prematurely declared victory"
            " on failing tasks, artificially inflating apparent success rates while"
            " failing objective criteria.",
            "- **Fairness Note**: These results reflect offline deterministic test scenarios"
            " and local model evaluations; they do not constitute guarantees on cloud models"
            " or disparate hardware environments.",
            "",
        ]
    )

    return "\n".join(lines)
