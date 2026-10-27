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


def test_onboarding_health_and_webapp_sample_endpoints() -> None:
    assert client.get("/api/onboard/health").json()["status"] == "ok"
    sample = client.get("/webapp/sample_ticket.json")
    assert sample.status_code == 200
    assert "tsd_" in sample.text


def test_root_uses_universal_console_and_classic_console_is_preserved() -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert "Upload one record" in root.text
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert "TaskSentry Console" in client.get("/classic/").text


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


def test_domain_autonomy_panel_endpoints_are_fail_closed() -> None:
    response = client.get("/api/domain/autonomy?tenant_id=console-test")
    assert response.status_code == 200
    data = response.json()
    assert data["policy"]["levels"]["system_write"] == "L3"
    assert data["pending_approvals"] == []

    updated = client.put(
        "/api/domain/autonomy",
        json={"tenant_id": "console-test", "levels": {"read": "L1"}},
    )
    assert updated.status_code == 200
    assert updated.json()["policy"]["levels"]["read"] == "L1"

    killed = client.post("/api/domain/autonomy/kill-switch?tenant_id=console-test&enabled=true")
    assert killed.status_code == 200 and killed.json()["kill_switch"] is True


def test_domain_review_and_shadow_proposal_endpoints_require_explicit_review() -> None:
    review = client.post(
        "/api/domain/reviews",
        json={
            "tenant_id": "console-review",
            "kind": "remediation",
            "name": "redeploy_du",
            "risk_tier": "system_write",
            "payload": {"command_id": "redeploy_du"},
        },
    )
    assert review.status_code == 201
    review_id = review.json()["review_id"]
    assert (
        client.get("/api/domain/reviews?tenant_id=console-review").json()["reviews"][0]["status"]
        == "pending"
    )
    approved = client.post(f"/api/domain/reviews/{review_id}/approve", json={"note": "lab only"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    proposal = client.post(
        "/api/domain/proposals",
        json={
            "tenant_id": "console-review",
            "command_id": "redeploy_du",
            "risk_tier": "system_write",
            "args": {"target": "du-1"},
        },
    )
    assert proposal.status_code == 201
    assert client.get("/api/domain/proposals?tenant_id=console-review").json()["proposals"]


def test_governance_tab_uses_safe_dom_rendering() -> None:
    html = client.get("/").text
    script = client.get("/app.js").text
    assert 'data-tab="governance"' in html
    assert "autonomyLevels" in html and "shadowProposals" in html
    assert "replaceChildren" in script and "loadGovernance" in script


def test_cloud_recognition_requires_explicit_tenant_opt_in() -> None:
    refused = client.post(
        "/api/onboard/analyze",
        json={
            "record": '{"id":"t1"}',
            "tenant_id": "regulated",
            "use_llm": True,
            "model": "beam:cloud",
        },
    )
    assert refused.status_code == 422
    assert "opt-in" in refused.json()["detail"]
