"""Unit tests for Console receipt generation and downloads."""

from fastapi.testclient import TestClient

from tasksentry.console.app import create_console_app
from tasksentry.console.runs import default_run_manager
from tasksentry.core.receipt import TaskReceipt
from tasksentry.storage.sqlite import SQLiteReceiptStore

app = create_console_app()
client = TestClient(app)


def test_get_receipt_for_active_run_with_receipt() -> None:
    run = default_run_manager.create_run("t_rec_1", "Goal 1")
    rec = TaskReceipt(
        task_id="t_rec_1",
        status="completed",
        success=True,
        tokens=1250,
        cost_usd=0.002,
        wall_time_seconds=3.5,
    )
    run.receipt = rec

    res = client.get("/api/chat/tasks/t_rec_1/receipt")
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "t_rec_1"
    assert data["tokens"] == 1250
    assert data["success"] is True


def test_get_receipt_for_uncompleted_run_raises_404() -> None:
    run = default_run_manager.create_run("t_unfin", "Goal unfin")
    run.receipt = None
    res = client.get("/api/chat/tasks/t_unfin/receipt")
    assert res.status_code == 404


def test_get_receipt_from_sqlite_store_fallback() -> None:
    store = SQLiteReceiptStore("tasksentry.db")
    rec = TaskReceipt(
        task_id="t_from_db",
        status="completed",
        success=True,
        tokens=500,
        cost_usd=0.0,
    )
    store.save(rec)

    res = client.get("/api/chat/tasks/t_from_db/receipt")
    assert res.status_code == 200
    assert res.json()["task_id"] == "t_from_db"


def test_receipt_contains_required_fields() -> None:
    run = default_run_manager.create_run("t_rec_fields", "Goal")
    rec = TaskReceipt(
        task_id="t_rec_fields",
        status="completed",
        success=True,
        tokens=420,
        cost_usd=0.001,
        wall_time_seconds=1.2,
        tool_calls=2,
    )
    run.receipt = rec

    res = client.get("/api/chat/tasks/t_rec_fields/receipt")
    data = res.json()
    assert "tokens" in data
    assert "cost_usd" in data
    assert "wall_time_seconds" in data
    assert "tool_calls" in data
    assert "status" in data
