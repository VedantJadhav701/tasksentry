"""FastAPI REST API router for the TaskSentry local dashboard."""

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException

from tasksentry.config import load_config
from tasksentry.models.ollama import check_ollama_health
from tasksentry.storage.sqlite import SQLiteReceiptStore

router = APIRouter(prefix="/api")


def _get_store() -> SQLiteReceiptStore:
    cfg = load_config()
    return SQLiteReceiptStore(cfg.database_path)


@router.get("/health")
def get_health() -> dict[str, Any]:
    """Health status and basic service metadata."""
    return {
        "status": "healthy",
        "service": "tasksentry-dashboard",
        "bind_host": "127.0.0.1",
    }


@router.get("/tasks")
def list_tasks(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List stored tasks with status, tokens, cost, and duration."""
    store = _get_store()
    receipts = store.list_tasks(status=status, limit=limit)
    return [r.model_dump() for r in receipts]


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    """Retrieve full task detail including contract, timeline, and results."""
    store = _get_store()
    record = store.get_record(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return record


@router.get("/tasks/{task_id}/receipt")
def get_task_receipt(task_id: str) -> dict[str, Any]:
    """Retrieve final execution receipt for a task."""
    store = _get_store()
    receipt = store.get(task_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Receipt for '{task_id}' not found.")
    return receipt.model_dump()


@router.get("/tasks/{task_id}/events")
def get_task_events(task_id: str) -> list[dict[str, Any]]:
    """Retrieve lifecycle events recorded for a task."""
    store = _get_store()
    receipt = store.get(task_id)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return receipt.events


@router.get("/metrics")
def get_dashboard_metrics() -> dict[str, Any]:
    """Aggregate dashboard metrics over all stored executions."""
    store = _get_store()
    all_receipts = store.list_tasks(limit=500)
    total = len(all_receipts)
    if total == 0:
        return {
            "total_tasks": 0,
            "success_rate": 0.0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "duplicate_calls_blocked": 0,
        }

    successes = sum(1 for r in all_receipts if r.success)
    total_tokens = sum(r.tokens for r in all_receipts)
    total_cost = sum(r.cost_usd for r in all_receipts)
    blocked_dups = sum(r.duplicate_calls_blocked for r in all_receipts)

    return {
        "total_tasks": total,
        "success_rate": round(successes / total, 4),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "duplicate_calls_blocked": blocked_dups,
    }


@router.get("/benchmarks")
def list_benchmarks() -> list[dict[str, Any]]:
    """List available benchmark reports."""
    reports_dir = "reports"
    runs: list[dict[str, Any]] = []
    if os.path.isdir(reports_dir):
        for f in os.listdir(reports_dir):
            if f.endswith(".json") and f != "tasks":
                p = os.path.join(reports_dir, f)
                try:
                    with open(p, encoding="utf-8") as fp:
                        data = json.load(fp)
                        runs.append(
                            {
                                "run_id": f.replace(".json", ""),
                                "file": f,
                                "metadata": data.get("metadata", {}),
                                "aggregates": data.get("aggregates", {}),
                            }
                        )
                except Exception:
                    pass
    return runs


@router.get("/benchmarks/{run_id}")
def get_benchmark_run(run_id: str) -> dict[str, Any]:
    """Retrieve full details of a specific benchmark run."""
    reports_dir = "reports"
    candidates = [
        os.path.join(reports_dir, f"{run_id}.json"),
        os.path.join(reports_dir, run_id),
    ]
    for p in candidates:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fp:
                return json.load(fp)  # type: ignore[no-any-return]
    raise HTTPException(status_code=404, detail=f"Benchmark run '{run_id}' not found.")


@router.get("/ollama/models")
def get_ollama_models() -> dict[str, Any]:
    """Query health and available models from local Ollama instance."""
    return check_ollama_health()


@router.post("/tasks/{task_id}/stop")
def stop_task(task_id: str) -> dict[str, Any]:
    """Request early termination of an active task."""
    from tasksentry.console.runs import default_run_manager

    # If running in active console background runner, signal stop
    live_run = default_run_manager.get(task_id)
    if live_run:
        live_run.request_stop()

    store = _get_store()
    receipt = store.get(task_id)
    if not receipt:
        if live_run:
            return {"status": "stopped", "task_id": task_id}
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    updated = receipt.model_copy(
        update={"status": "stopped", "final_status": "stopped", "success": False}
    )
    store.update(updated)
    return {"status": "stopped", "task_id": task_id}


@router.get("/console/status")
def get_console_status() -> dict[str, Any]:
    """Report console runner status, active background runs, and pending approvals."""
    from tasksentry.console.runs import default_run_manager

    runs = default_run_manager.list_runs(limit=10)
    active_statuses = ("running", "waiting_approval")
    active_count = len([r for r in runs if r.get("status") in active_statuses])
    return {
        "active_runs_count": active_count,
        "recent_runs": runs,
    }
