"""Unit tests for the CLI subcommands."""

import os

import pytest

from tasksentry.cli import main
from tasksentry.core.receipt import TaskReceipt
from tasksentry.storage.sqlite import SQLiteReceiptStore


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--help"])
    assert code == 0
    captured = capsys.readouterr()
    assert "TaskSentry" in captured.out
    assert "demo" in captured.out
    assert "run" in captured.out
    assert "tasks" in captured.out


def test_cli_demo(
    tmp_path: os.PathLike[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_file = os.path.join(str(tmp_path), "demo.db")
    monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", db_file)

    code = main(["demo"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Task Sentry Receipt" in captured.out
    assert "Status:" in captured.out


def test_cli_run(
    tmp_path: os.PathLike[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_file = os.path.join(str(tmp_path), "run.db")
    monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", db_file)

    task_yaml = os.path.join(str(tmp_path), "task.yaml")
    with open(task_yaml, "w", encoding="utf-8") as f:
        f.write(
            """
goal: "Test CLI run command"
budget:
  max_llm_calls: 5
  max_tool_calls: 5
success_criteria:
  - id: "crit1"
    verifier: "numeric_range"
    config:
      value: 10
      min: 0
"""
        )

    code = main(["run", "--task", task_yaml])
    assert code == 0
    captured = capsys.readouterr()
    assert "task_id" in captured.out


def test_cli_tasks_and_task_and_receipt(
    tmp_path: os.PathLike[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_file = os.path.join(str(tmp_path), "records.db")
    monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", db_file)

    store = SQLiteReceiptStore(db_file)
    store.save(TaskReceipt(task_id="cli_task_99", status="completed", tokens=450, cost_usd=0.01))

    # tasks
    code_list = main(["tasks"])
    assert code_list == 0
    cap_list = capsys.readouterr()
    assert "cli_task_99" in cap_list.out

    # task
    code_task = main(["task", "cli_task_99"])
    assert code_task == 0
    cap_task = capsys.readouterr()
    assert "cli_task_99" in cap_task.out

    # receipt
    code_rec = main(["receipt", "cli_task_99"])
    assert code_rec == 0
    cap_rec = capsys.readouterr()
    assert '"task_id": "cli_task_99"' in cap_rec.out
