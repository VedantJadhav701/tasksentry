"""Unit tests for the benchmark runner."""

import json
import os

from tasksentry.benchmark.runner import run_benchmark_suite


def test_run_benchmark_suite_offline(tmp_path: os.PathLike[str]) -> None:
    out_json = os.path.join(str(tmp_path), "reports", "offline-benchmark.json")

    data = run_benchmark_suite(
        suite_name="offline-v0.1",
        seed=123,
        output_path=out_json,
    )

    assert os.path.isfile(out_json)
    assert "metadata" in data
    out_md = out_json.replace(".json", ".md")
    assert os.path.isfile(out_md)

    with open(out_json, encoding="utf-8") as f:
        loaded = json.load(f)

    assert "metadata" in loaded
    assert loaded["metadata"]["seed"] == 123
    assert loaded["metadata"]["suite"] == "offline-v0.1"

    assert "aggregates" in loaded
    assert "react_baseline" in loaded["aggregates"]
    assert "tasksentry_case" in loaded["aggregates"]

    assert "case_ablations" in loaded
    assert "per_task_results" in loaded
    assert len(loaded["per_task_results"]) >= 25

    # Check tasks directory has task JSON files
    tasks_dir = os.path.join(str(tmp_path), "reports", "tasks")
    assert os.path.isdir(tasks_dir)
    assert len(os.listdir(tasks_dir)) >= 25


def test_runner_deterministic_seed_stability(tmp_path: os.PathLike[str]) -> None:
    out1 = os.path.join(str(tmp_path), "run1.json")
    out2 = os.path.join(str(tmp_path), "run2.json")

    run_benchmark_suite(seed=999, output_path=out1)
    run_benchmark_suite(seed=999, output_path=out2)

    with open(out1, encoding="utf-8") as f1, open(out2, encoding="utf-8") as f2:
        d1 = json.load(f1)
        d2 = json.load(f2)

    task_order_1 = [t["task_id"] for t in d1["per_task_results"]]
    task_order_2 = [t["task_id"] for t in d2["per_task_results"]]
    assert task_order_1 == task_order_2
