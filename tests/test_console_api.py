"""Unit tests for the Console FastAPI REST endpoints."""

from fastapi.testclient import TestClient

from tasksentry.console.app import create_console_app
from tasksentry.console.approvals import default_approval_manager
from tasksentry.console.runs import default_run_manager

app = create_console_app()
client = TestClient(app)


def test_post_chat_tasks_success() -> None:
    res = client.post(
        "/api/chat/tasks",
        json={"message": "Run tests and verify build", "mock_mode": True},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["task_id"].startswith("task_")
    assert data["status"] in ("created", "running", "completed")
    assert data["goal"] == "Run tests and verify build"


def test_post_chat_tasks_empty_message_400() -> None:
    res = client.post("/api/chat/tasks", json={"message": "   "})
    assert res.status_code == 400


def test_get_chat_tasks_list() -> None:
    res = client.get("/api/chat/tasks?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "tasks" in data
    assert "count" in data


def test_get_chat_task_by_id() -> None:
    create_res = client.post(
        "/api/chat/tasks",
        json={"message": "Inspect repository files", "mock_mode": True},
    )
    task_id = create_res.json()["task_id"]

    res = client.get(f"/api/chat/tasks/{task_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == task_id
    assert data["goal"] == "Inspect repository files"
    assert "events" in data


def test_get_chat_task_not_found_404() -> None:
    res = client.get("/api/chat/tasks/nonexistent_task_999")
    assert res.status_code == 404


def test_post_task_approve_success() -> None:
    default_run_manager.create_run("t_appr", "Goal")
    req = default_approval_manager.request_approval("t_appr", "write_file", {"p": "a"})

    res = client.post(
        "/api/chat/tasks/t_appr/approve",
        json={"approval_id": req.approval_id},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "approved"


def test_post_task_reject_success() -> None:
    default_run_manager.create_run("t_rej", "Goal")
    req = default_approval_manager.request_approval("t_rej", "rm_file", {"p": "b"})

    res = client.post(
        "/api/chat/tasks/t_rej/reject",
        json={"approval_id": req.approval_id, "reason": "Unsafe action blocked."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert res.json()["reason"] == "Unsafe action blocked."


def test_post_task_stop_success() -> None:
    default_run_manager.create_run("t_stop_api", "Goal")
    res = client.post("/api/chat/tasks/t_stop_api/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "stopped"


def test_get_models_health_endpoint() -> None:
    res = client.get("/api/chat/models")
    assert res.status_code == 200
    data = res.json()
    assert "reachable" in data
    assert "available_models" in data
    assert "models_metadata" in data


def test_get_routing_audit_endpoint() -> None:
    res = client.get("/api/chat/routing/task_test_routing")
    assert res.status_code == 200
    data = res.json()
    assert data["task_id"] == "task_test_routing"
    assert "decisions" in data


def test_post_playground_compare_endpoint() -> None:
    res = client.post(
        "/api/chat/playground/compare",
        json={
            "prompt": "Investigate root cause of memory spike",
            "mock_mode": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["lane_selected"] == "reasoning"
    assert "routine_lane" in data
    assert "reasoning_lane" in data
    assert "routed_response" in data
