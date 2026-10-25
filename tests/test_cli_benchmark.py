"""Unit tests for Phase 5 CLI extensions (benchmark, ollama-health, benchmark-report)."""

import os

import pytest

from tasksentry.cli import main


def test_cli_benchmark_offline(
    tmp_path: os.PathLike[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_file = os.path.join(str(tmp_path), "bench.json")
    code = main(["benchmark", "--suite", "offline-v0.1", "--output", out_file])
    assert code == 0
    assert os.path.isfile(out_file)
    captured = capsys.readouterr()
    assert "TaskSentryBench" in captured.out
    assert "Benchmark finished" in captured.out


def test_cli_ollama_health(capsys: pytest.CaptureFixture[str]) -> None:
    # Run against non-existent URL or probe
    main(["ollama-health", "--base-url", "http://127.0.0.1:99999/v1"])
    captured = capsys.readouterr()
    assert "Ollama Health Status" in captured.out
    assert "Reachable:" in captured.out


def test_cli_benchmark_report(
    tmp_path: os.PathLike[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rep_dir = os.path.join(str(tmp_path), "reports")
    os.makedirs(rep_dir, exist_ok=True)
    report_file = os.path.join(rep_dir, "sample_run.md")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# Sample Run Benchmark Report\nSummary here.")

    monkeypatch.chdir(tmp_path)
    code = main(["benchmark-report", "--run", "sample_run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Sample Run Benchmark Report" in captured.out
