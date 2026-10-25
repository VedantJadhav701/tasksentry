"""Unit tests for benchmark tasks and baselines."""

from tasksentry.benchmark.baselines import BenchmarkBaselineRunner
from tasksentry.benchmark.suites.offline_v01 import get_offline_v01_tasks
from tasksentry.benchmark.suites.ollama_v01 import get_ollama_v01_tasks


def test_offline_suite_task_count_and_families() -> None:
    tasks = get_offline_v01_tasks()
    assert len(tasks) >= 25

    families = {t.family for t in tasks}
    expected_families = {
        "Code repair",
        "Repository analysis",
        "RAG-style research",
        "Multi-step API workflow",
        "Injected transient tool failures",
        "Duplicate-call traps",
        "Context-bloat traps",
        "Premature-completion traps",
        "Budget-constrained planning",
        "Recovery-from-failure tasks",
    }
    assert expected_families.issubset(families)


def test_ollama_suite_task_consistency() -> None:
    off_tasks = get_offline_v01_tasks()
    ollama_tasks = get_ollama_v01_tasks()
    assert len(off_tasks) == len(ollama_tasks)
    assert [t.task_id for t in off_tasks] == [t.task_id for t in ollama_tasks]


def test_baseline_runner_all_systems() -> None:
    tasks = get_offline_v01_tasks()
    task = next(t for t in tasks if t.task_id == "cr_syntax_error")

    runner = BenchmarkBaselineRunner(task)
    results = runner.run_all_systems()

    assert "react_baseline" in results
    assert "baseline_safeguards" in results
    assert "baseline_reflection" in results
    assert "tasksentry_case" in results
    assert "case_ablation_no_apg" in results
    assert "case_ablation_no_verification" in results

    assert results["tasksentry_case"]["success"] is True


def test_duplicate_trap_intervention() -> None:
    tasks = get_offline_v01_tasks()
    task = next(t for t in tasks if t.task_id == "dup_search_loop")

    runner = BenchmarkBaselineRunner(task)
    results = runner.run_all_systems()

    case_res = results["tasksentry_case"]
    assert case_res["duplicate_tool_calls"] >= 1


def test_premature_completion_trap_handling() -> None:
    tasks = get_offline_v01_tasks()
    task = next(t for t in tasks if t.task_id == "premature_claim_early")

    runner = BenchmarkBaselineRunner(task)
    results = runner.run_all_systems()

    # Without verification gate, completion claim passes immediately!
    assert results["case_ablation_no_verification"]["success"] is True
