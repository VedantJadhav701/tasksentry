"""Unit tests for Console Chat session and run orchestration."""

from tasksentry.console.chat import (
    ChatBudgetConfig,
    ChatSessionManager,
    ChatTaskRequest,
)
from tasksentry.console.runs import ConsoleRunManager


def test_chat_budget_config_defaults() -> None:
    cfg = ChatBudgetConfig()
    assert cfg.max_tokens == 60000
    assert cfg.max_tool_calls == 15
    assert cfg.max_cost_usd == 0.50
    assert cfg.max_wall_time_seconds == 300.0


def test_chat_task_request_validation() -> None:
    req = ChatTaskRequest(
        message="Refactor math module",
        routine_model="qwen2.5:3b",
        reasoning_model="qwen3:4b-instruct-2507-q4_K_M",
        allow_writes=True,
    )
    assert req.message == "Refactor math module"
    assert req.allow_writes is True
    assert req.routine_model == "qwen2.5:3b"


def test_chat_session_manager_submit_task() -> None:
    mgr = ChatSessionManager()
    req = ChatTaskRequest(
        message="Find and fix bugs in tests",
        mock_mode=True,
    )
    run = mgr.submit_task(req)
    assert run.task_id.startswith("task_")
    assert run.goal == "Find and fix bugs in tests"
    assert run.status in ("created", "running", "completed")


def test_chat_session_manager_stores_initial_user_message() -> None:
    mgr = ChatSessionManager()
    req = ChatTaskRequest(message="Initial user query", mock_mode=True)
    run = mgr.submit_task(req)

    history = mgr.get_messages(run.task_id)
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Initial user query"


def test_chat_run_manager_list_runs() -> None:
    run_mgr = ConsoleRunManager()
    run_mgr.create_run("t1", "Goal 1")
    run_mgr.create_run("t2", "Goal 2")

    runs = run_mgr.list_runs(limit=10)
    assert len(runs) >= 2
    task_ids = [r["task_id"] for r in runs]
    assert "t1" in task_ids
    assert "t2" in task_ids


def test_chat_run_manager_get_run() -> None:
    run_mgr = ConsoleRunManager()
    created = run_mgr.create_run("t_find", "Goal find")
    found = run_mgr.get("t_find")
    assert found is not None
    assert found.task_id == created.task_id
    assert run_mgr.get("nonexistent") is None


def test_chat_run_stop_request() -> None:
    run_mgr = ConsoleRunManager()
    run = run_mgr.create_run("t_stop", "Goal stop")
    assert run.is_stopped() is False
    run.request_stop()
    assert run.is_stopped() is True
    assert run.status == "stopped"
