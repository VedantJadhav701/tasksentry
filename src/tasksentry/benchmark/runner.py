"""TaskSentry benchmark runner orchestrating task execution across all 6 systems."""

import argparse
import datetime
import json
import os
import random
import sys
from typing import Any

from tasksentry.benchmark.baselines import BenchmarkBaselineRunner
from tasksentry.benchmark.metrics import calculate_metrics
from tasksentry.benchmark.report import generate_markdown_report
from tasksentry.benchmark.suites.offline_v01 import get_offline_v01_tasks
from tasksentry.benchmark.suites.ollama_v01 import get_ollama_v01_tasks
from tasksentry.models.ollama import OllamaClient
from tasksentry.version import __version__


def run_benchmark_suite(
    suite_name: str = "offline-v0.1",
    routine_model: str = "llama3.2:1b",
    reasoning_model: str = "qwen3:4b-instruct-2507-q4_K_M",
    seed: int = 42,
    output_path: str = "reports/benchmark.json",
    ollama_base_url: str = "http://localhost:11434/v1",
) -> dict[str, Any]:
    """Execute the full benchmark suite across all 6 systems and generate reports."""
    random.seed(seed)

    # 1. Select tasks
    if "ollama" in suite_name.lower():
        tasks = get_ollama_v01_tasks()
        model_client = OllamaClient(model=routine_model, base_url=ollama_base_url)
    else:
        tasks = get_offline_v01_tasks()
        model_client = None

    # Shuffle deterministically
    shuffled_tasks = list(tasks)
    random.shuffle(shuffled_tasks)

    system_results: dict[str, list[dict[str, Any]]] = {
        "react_baseline": [],
        "baseline_safeguards": [],
        "baseline_reflection": [],
        "tasksentry_case": [],
        "case_ablation_no_apg": [],
        "case_ablation_no_verification": [],
    }

    per_task_records: list[dict[str, Any]] = []

    # Prepare output directories
    out_dir = os.path.dirname(output_path) or "reports"
    tasks_dir = os.path.join(out_dir, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    for task in shuffled_tasks:
        runner = BenchmarkBaselineRunner(task, model_client=model_client)
        task_outcomes = runner.run_all_systems()

        for sys_name, res in task_outcomes.items():
            system_results[sys_name].append(res)

        record = {
            "task_id": task.task_id,
            "family": task.family,
            "goal": task.goal,
            "results": task_outcomes,
        }
        per_task_records.append(record)

        # Save individual task JSON
        task_file = os.path.join(tasks_dir, f"{task.task_id}.json")
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

    # Calculate metrics for each system
    aggregates: dict[str, dict[str, Any]] = {}
    for sys_name, results in system_results.items():
        m = calculate_metrics(results)
        aggregates[sys_name] = m.model_dump()

    case_ablations = {
        "tasksentry_case": aggregates["tasksentry_case"],
        "case_ablation_no_apg": aggregates["case_ablation_no_apg"],
        "case_ablation_no_verification": aggregates["case_ablation_no_verification"],
    }

    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    meta = {
        "timestamp": now_iso,
        "suite": suite_name,
        "seed": seed,
        "python_version": sys.version.split()[0],
        "tasksentry_version": __version__,
        "ollama_base_url": ollama_base_url if "ollama" in suite_name else "N/A",
        "routine_model": routine_model if "ollama" in suite_name else "N/A",
        "reasoning_model": reasoning_model if "ollama" in suite_name else "N/A",
        "hardware": "Local execution environment",
    }

    benchmark_data = {
        "metadata": meta,
        "aggregates": aggregates,
        "case_ablations": case_ablations,
        "per_task_results": per_task_records,
    }

    # Write output JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, indent=2)

    # Write output Markdown
    md_path = output_path.replace(".json", ".md")
    md_content = generate_markdown_report(benchmark_data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    return benchmark_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasksentry.benchmark.runner",
        description="Run TaskSentryBench v0.1 comparison across 6 systems.",
    )
    parser.add_argument(
        "--suite",
        "-s",
        default="offline-v0.1",
        choices=["offline-v0.1", "ollama-v0.1", "v0.1"],
        help="Benchmark suite to run",
    )
    parser.add_argument(
        "--routine-model",
        default="llama3.2:1b",
        help="Routine lane Ollama model",
    )
    parser.add_argument(
        "--reasoning-model",
        default="qwen3:4b-instruct-2507-q4_K_M",
        help="Reasoning lane Ollama model",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="reports/benchmark.json",
        help="Path for destination JSON report",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434/v1",
        help="Ollama base URL",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    suite = args.suite
    if suite == "v0.1":
        suite = "offline-v0.1"

    print(f"Starting TaskSentryBench v0.1: suite='{suite}', seed={args.seed}")
    data = run_benchmark_suite(
        suite_name=suite,
        routine_model=args.routine_model,
        reasoning_model=args.reasoning_model,
        seed=args.seed,
        output_path=args.output,
        ollama_base_url=args.base_url,
    )
    meta = data["metadata"]
    print(f"Benchmark completed successfully at {meta['timestamp']}")
    print(f"JSON report: {args.output}")
    print(f"Markdown report: {args.output.replace('.json', '.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
