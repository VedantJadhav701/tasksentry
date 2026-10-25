"""Unit tests for the Human-in-the-Loop Approval Manager."""

import threading
import time

import pytest

from tasksentry.console.approvals import ApprovalManager


def test_create_approval_request() -> None:
    mgr = ApprovalManager()
    req = mgr.request_approval(
        task_id="t1",
        tool="write_text_file",
        arguments={"path": "test.txt", "content": "hello"},
        risk="reversible_write",
        reason="Writing file",
    )
    assert req.task_id == "t1"
    assert req.tool == "write_text_file"
    assert req.status == "pending"
    assert req.approval_id.startswith("appr_")


def test_approve_flow_signals_event() -> None:
    mgr = ApprovalManager()
    req = mgr.request_approval("t1", "edit_file", {"path": "main.py"})

    # Worker thread to approve
    def _approve_delayed() -> None:
        time.sleep(0.05)
        mgr.approve(req.approval_id)

    threading.Thread(target=_approve_delayed, daemon=True).start()

    resolved = mgr.wait_for_decision(req.approval_id, timeout_seconds=2.0)
    assert resolved.status == "approved"
    assert resolved.resolved_at is not None


def test_reject_flow_signals_event() -> None:
    mgr = ApprovalManager()
    req = mgr.request_approval("t1", "delete_file", {"path": "main.py"})

    def _reject_delayed() -> None:
        time.sleep(0.05)
        mgr.reject(req.approval_id, reason="Denied by user safety policy")

    threading.Thread(target=_reject_delayed, daemon=True).start()

    resolved = mgr.wait_for_decision(req.approval_id, timeout_seconds=2.0)
    assert resolved.status == "rejected"
    assert resolved.resolution_reason == "Denied by user safety policy"


def test_approval_timeout() -> None:
    mgr = ApprovalManager()
    req = mgr.request_approval("t1", "drop_db", {})
    resolved = mgr.wait_for_decision(req.approval_id, timeout_seconds=0.05)
    assert resolved.status == "timed_out"
    assert "timed out" in (resolved.resolution_reason or "")


def test_get_pending_approvals_for_task() -> None:
    mgr = ApprovalManager()
    r1 = mgr.request_approval("task_a", "tool1", {})
    r2 = mgr.request_approval("task_a", "tool2", {})
    mgr.request_approval("task_b", "tool3", {})

    pending_a = mgr.get_pending_for_task("task_a")
    assert len(pending_a) == 2
    assert {r.approval_id for r in pending_a} == {r1.approval_id, r2.approval_id}

    # Approve r1
    mgr.approve(r1.approval_id)
    pending_a_after = mgr.get_pending_for_task("task_a")
    assert len(pending_a_after) == 1
    assert pending_a_after[0].approval_id == r2.approval_id


def test_double_approval_rejected() -> None:
    mgr = ApprovalManager()
    req = mgr.request_approval("t1", "tool", {})
    ok1 = mgr.approve(req.approval_id)
    ok2 = mgr.approve(req.approval_id)
    assert ok1 is True
    assert ok2 is False


def test_wait_for_decision_nonexistent_raises() -> None:
    mgr = ApprovalManager()
    with pytest.raises(KeyError):
        mgr.wait_for_decision("nonexistent_id", timeout_seconds=0.1)


def test_list_approvals_for_task() -> None:
    mgr = ApprovalManager()
    r1 = mgr.request_approval("task_z", "tool1", {})
    r2 = mgr.request_approval("task_z", "tool2", {})
    mgr.approve(r1.approval_id)
    mgr.reject(r2.approval_id)

    all_reqs = mgr.list_for_task("task_z")
    assert len(all_reqs) == 2
    statuses = {r.status for r in all_reqs}
    assert statuses == {"approved", "rejected"}
