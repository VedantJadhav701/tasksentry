"""Unit tests for Console model health, metadata, and dashboard status."""

from fastapi.testclient import TestClient

from tasksentry.console.app import create_console_app
from tasksentry.console.runs import default_run_manager

app = create_console_app()
client = TestClient(app)


def test_models_health_structure() -> None:
    res = client.get("/api/chat/models")
    assert res.status_code == 200
    data = res.json()
    assert "reachable" in data
    assert "base_url" in data
    assert "available_models" in data
    assert isinstance(data["models_metadata"], list)


def test_model_lane_classification_in_api() -> None:
    res = client.get("/api/chat/models")
    data = res.json()
    for m in data["models_metadata"]:
        assert m["lane"] in ("routine", "reasoning")
        assert "context_window" in m
        assert m["context_window"] > 0


def test_default_routine_and_reasoning_models() -> None:
    res = client.get("/api/chat/models")
    data = res.json()
    assert data["default_routine_model"] == "qwen2.5:3b"
    assert data["default_reasoning_model"] == "qwen3:4b-instruct-2507-q4_K_M"


def test_models_metadata_context_window() -> None:
    res = client.get("/api/chat/models")
    data = res.json()
    for m in data["models_metadata"]:
        if "qwen3" in m["name"]:
            # Ensure safe 4096 context window limit is assigned
            assert m["context_window"] == 4096


def test_dashboard_console_status_endpoint() -> None:
    default_run_manager.create_run("t_status_check", "Goal")
    res = client.get("/api/console/status")
    assert res.status_code == 200
    data = res.json()
    assert "active_runs_count" in data
    assert "recent_runs" in data
