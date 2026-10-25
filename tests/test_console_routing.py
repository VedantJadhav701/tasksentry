"""Unit tests for the Console Semantic Routing Inspector and Playground."""

from tasksentry.console.routing import (
    RouterAuditLog,
    RouterPlayground,
    RoutingDecision,
)
from tasksentry.models.router import SemanticModelRouter


def test_router_audit_log_record_and_get() -> None:
    audit = RouterAuditLog()
    dec1 = RoutingDecision(
        step=1,
        selected_model="qwen2.5:3b",
        lane="routine",
        reason="routine tool execution",
        signals={"complexity": "standard"},
        fallback_model="qwen3:4b-instruct-2507-q4_K_M",
        latency_ms=85.0,
        tokens={"input": 120, "output": 25},
    )
    audit.record("task_123", dec1)

    decisions = audit.get_task_decisions("task_123")
    assert len(decisions) == 1
    assert decisions[0].selected_model == "qwen2.5:3b"
    assert decisions[0].lane == "routine"


def test_router_audit_log_clear() -> None:
    audit = RouterAuditLog()
    audit.record("t1", RoutingDecision(step=1, selected_model="m", lane="r", reason=""))
    assert len(audit.get_task_decisions("t1")) == 1
    audit.clear()
    assert len(audit.get_task_decisions("t1")) == 0


def test_router_playground_mock_routine_decision() -> None:
    router = SemanticModelRouter(routine_model="qwen2.5:3b", reasoning_model="qwen3:4b")
    playground = RouterPlayground(router=router, mock_mode=True)

    res = playground.compare(prompt="List files in the working directory.")
    assert res["lane_selected"] == "routine"
    assert res["selected_model"] == "qwen2.5:3b"
    assert "routine" in res["routine_lane"]["content"].lower()
    assert res["signals"]["complexity"] == "standard"


def test_router_playground_mock_reasoning_decision() -> None:
    router = SemanticModelRouter(routine_model="qwen2.5:3b", reasoning_model="qwen3:4b")
    playground = RouterPlayground(router=router, mock_mode=True)

    prompt = "Investigate root cause of failure and plan architectural refactoring"
    res = playground.compare(prompt=prompt)
    assert res["lane_selected"] == "reasoning"
    assert res["selected_model"] == "qwen3:4b"
    assert res["signals"]["complexity"] == "hard"
    assert res["fallback_model"] == "qwen2.5:3b"


def test_router_playground_signals_complexity() -> None:
    playground = RouterPlayground(mock_mode=True)
    res = playground.compare(
        prompt="diagnose why verification failed",
        context={"verification_failed": True, "stagnant_steps": 2},
    )
    assert res["signals"]["open_failures"] == 1
    assert res["signals"]["stagnant_steps"] == 2
    assert res["lane_selected"] == "reasoning"


def test_router_decision_model_dump() -> None:
    d = RoutingDecision(
        step=3,
        selected_model="ornith:latest",
        lane="reasoning",
        reason="diagnostics",
        signals={"complexity": "hard"},
    )
    data = d.model_dump()
    assert data["step"] == 3
    assert data["selected_model"] == "ornith:latest"
    assert data["lane"] == "reasoning"
