"""Unit tests for the local dashboard FastAPI endpoints."""

import os

import pytest
from fastapi.testclient import TestClient

from tasksentry.core.receipt import TaskReceipt
from tasksentry.dashboard.app import app
from tasksentry.storage.sqlite import SQLiteReceiptStore


def test_dashboard_health() -> None:
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["bind_host"] == "127.0.0.1"


def test_dashboard_tasks_and_detail(
    tmp_path: os.PathLike[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = os.path.join(str(tmp_path), "dash.db")
    monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", db_file)

    store = SQLiteReceiptStore(db_file)
    store.save(
        TaskReceipt(
            task_id="task_dash_1",
            status="completed",
            tokens=350,
            cost_usd=0.015,
            events=[{"type": "BUDGET_WARNING", "message": "Near limit"}],
        )
    )

    client = TestClient(app)

    # List tasks
    res_list = client.get("/api/tasks")
    assert res_list.status_code == 200
    tasks = res_list.json()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "task_dash_1"

    # Detail
    res_detail = client.get("/api/tasks/task_dash_1")
    assert res_detail.status_code == 200
    record = res_detail.json()
    assert record["task_id"] == "task_dash_1"

    # Receipt
    res_receipt = client.get("/api/tasks/task_dash_1/receipt")
    assert res_receipt.status_code == 200
    assert res_receipt.json()["tokens"] == 350

    # Events
    res_events = client.get("/api/tasks/task_dash_1/events")
    assert res_events.status_code == 200
    assert len(res_events.json()) == 1

    # Stop task
    res_stop = client.post("/api/tasks/task_dash_1/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["status"] == "stopped"


def test_dashboard_metrics(tmp_path: os.PathLike[str], monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = os.path.join(str(tmp_path), "metrics.db")
    monkeypatch.setenv("TASKSENTRY_DATABASE_PATH", db_file)

    store = SQLiteReceiptStore(db_file)
    store.save(TaskReceipt(task_id="t1", status="completed", tokens=100, cost_usd=0.01))
    store.save(TaskReceipt(task_id="t2", status="completed", tokens=200, cost_usd=0.02))

    client = TestClient(app)
    res = client.get("/api/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["total_tasks"] == 2
    assert data["total_tokens"] == 300
    assert data["success_rate"] == 1.0


def test_dashboard_ollama_models() -> None:
    client = TestClient(app)
    res = client.get("/api/ollama/models")
    assert res.status_code == 200
    data = res.json()
    assert "reachable" in data
    assert "available" in data
