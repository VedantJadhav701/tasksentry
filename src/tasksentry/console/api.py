"""FastAPI router implementing the chat, streaming, routing, approvals, and playground APIs."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from tasksentry.console.approvals import default_approval_manager
from tasksentry.console.chat import ChatTaskRequest, default_chat_manager
from tasksentry.console.routing import RouterPlayground, default_audit_log
from tasksentry.console.runs import default_run_manager
from tasksentry.console.sockets import handle_websocket_stream, sse_event_stream
from tasksentry.models.ollama import check_ollama_health
from tasksentry.storage.sqlite import SQLiteReceiptStore

router = APIRouter(prefix="/api/chat", tags=["Console"])


class ApprovalActionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    approval_id: str | None = None
    reason: str | None = None


class PlaygroundCompareRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt: str
    routine_model: str | None = None
    reasoning_model: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    mock_mode: bool = False


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_chat_task(req: ChatTaskRequest) -> dict[str, Any]:
    """Submit a task through the chat interface and start background execution."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Task message cannot be empty.")

    run = default_chat_manager.submit_task(req)
    return {
        "task_id": run.task_id,
        "status": run.status,
        "goal": run.goal,
        "created_at": run.created_at,
    }


@router.get("/tasks")
def list_tasks(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List recent console runs."""
    runs = default_run_manager.list_runs(limit=limit)
    return {"tasks": runs, "count": len(runs)}


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    """Get status, events, and pending approvals for a task."""
    run = default_run_manager.get(task_id)
    if not run:
        # Check persistent storage
        store = SQLiteReceiptStore("tasksentry.db")
        rec = store.get(task_id)
        if rec:
            return {
                "task_id": task_id,
                "status": rec.status,
                "goal": "Retrieved from persistent store",
                "events": [e.model_dump() if hasattr(e, "model_dump") else e for e in rec.events],
                "receipt": rec.model_dump(),
                "pending_approvals": [],
            }
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    pending_apprs = default_approval_manager.get_pending_for_task(task_id)
    return {
        "task_id": run.task_id,
        "goal": run.goal,
        "status": run.status,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "events": run.get_events(),
        "receipt": run.receipt.model_dump() if run.receipt else None,
        "pending_approvals": [a.model_dump() for a in pending_apprs],
    }


@router.get("/tasks/{task_id}/stream")
async def stream_task_events(task_id: str) -> StreamingResponse:
    """Server-Sent Events endpoint streaming real-time execution events."""
    run = default_run_manager.get(task_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    return StreamingResponse(
        sse_event_stream(run),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws/{task_id}")
async def websocket_task_stream(websocket: WebSocket, task_id: str) -> None:
    """WebSocket endpoint streaming task execution."""
    run = default_run_manager.get(task_id)
    if not run:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await handle_websocket_stream(websocket, run)


@router.post("/tasks/{task_id}/approve")
def approve_task_action(
    task_id: str,
    payload: ApprovalActionPayload | None = None,
) -> dict[str, Any]:
    """Approve a pending tool action."""
    run = default_run_manager.get(task_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    appr_id = payload.approval_id if payload else None
    if not appr_id:
        pending = default_approval_manager.get_pending_for_task(task_id)
        if not pending:
            raise HTTPException(status_code=400, detail="No pending approval found for this task.")
        appr_id = pending[0].approval_id

    success = default_approval_manager.approve(appr_id)
    if not success:
        detail = "Could not approve request (already resolved or invalid)."
        raise HTTPException(status_code=400, detail=detail)

    return {"status": "approved", "approval_id": appr_id, "task_id": task_id}


@router.post("/tasks/{task_id}/reject")
def reject_task_action(
    task_id: str,
    payload: ApprovalActionPayload | None = None,
) -> dict[str, Any]:
    """Reject a pending tool action."""
    run = default_run_manager.get(task_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    appr_id = payload.approval_id if payload else None
    reason = payload.reason if payload and payload.reason else "Action rejected by user."
    if not appr_id:
        pending = default_approval_manager.get_pending_for_task(task_id)
        if not pending:
            raise HTTPException(status_code=400, detail="No pending approval found for this task.")
        appr_id = pending[0].approval_id

    success = default_approval_manager.reject(appr_id, reason=reason)
    if not success:
        detail = "Could not reject request (already resolved or invalid)."
        raise HTTPException(status_code=400, detail=detail)

    return {"status": "rejected", "approval_id": appr_id, "task_id": task_id, "reason": reason}


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: str) -> dict[str, Any]:
    """Request early termination of a running task."""
    run = default_run_manager.get(task_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    run.request_stop()
    return {"status": "stopped", "task_id": task_id}


@router.get("/tasks/{task_id}/receipt")
def get_task_receipt(task_id: str) -> JSONResponse:
    """Download the final auditable task receipt JSON."""
    run = default_run_manager.get(task_id)
    if run and run.receipt:
        return JSONResponse(content=run.receipt.model_dump())

    store = SQLiteReceiptStore("tasksentry.db")
    rec = store.get(task_id)
    if rec:
        return JSONResponse(content=rec.model_dump())

    err = f"Receipt for task '{task_id}' not found or not completed."
    raise HTTPException(status_code=404, detail=err)


@router.get("/models")
def get_models_health(base_url: str = "http://127.0.0.1:11434/v1") -> dict[str, Any]:
    """Inspect local Ollama server health, latency, and installed models."""
    health = check_ollama_health(base_url=base_url)
    models_meta = []
    for mod in health.get("available_models", []):
        is_reasoning = any(r in mod for r in ["qwen3", "ornith", "beam", "deepseek"])
        rec_for = "planning & failure recovery" if is_reasoning else "routine tool execution"
        models_meta.append(
            {
                "name": mod,
                "lane": "reasoning" if is_reasoning else "routine",
                "context_window": 4096 if "qwen3" in mod else 8192,
                "recommended_for": rec_for,
            }
        )

    return {
        "reachable": health["reachable"],
        "base_url": health["base_url"],
        "latency_ms": health.get("latency_ms", 0.0),
        "available_models": health.get("available_models", []),
        "models_metadata": models_meta,
        "default_routine_model": "qwen2.5:3b",
        "default_reasoning_model": "qwen3:4b-instruct-2507-q4_K_M",
    }


@router.get("/routing/{task_id}")
def get_routing_audit(task_id: str) -> dict[str, Any]:
    """Get the auditable routing decisions for a task."""
    decisions = default_audit_log.get_task_decisions(task_id)
    return {
        "task_id": task_id,
        "count": len(decisions),
        "decisions": [d.model_dump() for d in decisions],
    }


@router.post("/playground/compare")
def compare_router_lanes(req: PlaygroundCompareRequest) -> dict[str, Any]:
    """Playground comparison testing prompt across routine, reasoning, and routed lanes."""
    playground = RouterPlayground(mock_mode=req.mock_mode)
    result = playground.compare(
        prompt=req.prompt,
        context=req.context,
        routine_model=req.routine_model,
        reasoning_model=req.reasoning_model,
    )
    return result
