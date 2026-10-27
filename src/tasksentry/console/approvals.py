"""Human-in-the-loop approval manager for potentially unsafe agent write actions."""

import threading
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalRequest(BaseModel):
    """Encapsulation of an action requiring explicit user confirmation."""

    model_config = ConfigDict(extra="ignore")

    approval_id: str = Field(default_factory=lambda: f"appr_{uuid.uuid4().hex[:8]}")
    task_id: str
    tool: str
    risk: str = "reversible_write"
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = "Write action requires user approval"
    status: str = "pending"  # "pending", "approved", "rejected", "timed_out"
    created_at: float = Field(default_factory=time.time)
    resolved_at: float | None = None
    resolution_reason: str | None = None


class ApprovalManager:
    """Thread-safe manager for tracking, pausing, and resolving tool approval gates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[str, ApprovalRequest] = {}
        self._events: dict[str, threading.Event] = {}
        self._by_task: dict[str, list[str]] = {}

    def request_approval(
        self,
        task_id: str,
        tool: str,
        arguments: dict[str, Any],
        risk: str = "reversible_write",
        reason: str = "Action requires confirmation",
    ) -> ApprovalRequest:
        """Create a pending approval request and register a wait event."""
        req = ApprovalRequest(
            task_id=task_id,
            tool=tool,
            risk=risk,
            arguments=arguments,
            reason=reason,
        )
        with self._lock:
            self._requests[req.approval_id] = req
            self._events[req.approval_id] = threading.Event()
            self._by_task.setdefault(task_id, []).append(req.approval_id)
        return req

    def wait_for_decision(
        self,
        approval_id: str,
        timeout_seconds: float = 300.0,
    ) -> ApprovalRequest:
        """Block the executing runner thread until user approves, rejects, or timeout expires."""
        with self._lock:
            evt = self._events.get(approval_id)
            req = self._requests.get(approval_id)

        if not evt or not req:
            raise KeyError(f"Approval request '{approval_id}' not found.")

        signaled = evt.wait(timeout=timeout_seconds)
        with self._lock:
            req = self._requests[approval_id]
            if not signaled and req.status == "pending":
                req.status = "timed_out"
                req.resolved_at = time.time()
                req.resolution_reason = "Approval timed out waiting for user response."
            return req

    def approve(self, approval_id: str) -> bool:
        """Approve the pending action and unblock the runner thread."""
        with self._lock:
            req = self._requests.get(approval_id)
            evt = self._events.get(approval_id)
            if not req or not evt or req.status != "pending":
                return False
            req.status = "approved"
            req.resolved_at = time.time()
            evt.set()
            return True

    def reject(self, approval_id: str, reason: str = "Rejected by user") -> bool:
        """Reject the pending action and unblock the runner thread with failure observation."""
        with self._lock:
            req = self._requests.get(approval_id)
            evt = self._events.get(approval_id)
            if not req or not evt or req.status != "pending":
                return False
            req.status = "rejected"
            req.resolved_at = time.time()
            req.resolution_reason = reason
            evt.set()
            return True

    def get(self, approval_id: str) -> ApprovalRequest | None:
        with self._lock:
            return self._requests.get(approval_id)

    def get_pending_for_task(self, task_id: str) -> list[ApprovalRequest]:
        with self._lock:
            appr_ids = self._by_task.get(task_id, [])
            return [
                self._requests[aid]
                for aid in appr_ids
                if aid in self._requests and self._requests[aid].status == "pending"
            ]

    def list_for_task(self, task_id: str) -> list[ApprovalRequest]:
        with self._lock:
            appr_ids = self._by_task.get(task_id, [])
            return [self._requests[aid] for aid in appr_ids if aid in self._requests]

    def list_pending(self) -> list[ApprovalRequest]:
        """Return every pending approval for the local governance panel."""
        with self._lock:
            return [request for request in self._requests.values() if request.status == "pending"]


# Shared global approval manager for console runtime
default_approval_manager = ApprovalManager()
