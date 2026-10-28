"""REST endpoints for universal onboarding. Mount with app.include_router(router)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from tasksentry.domain.redact import TenantRedactor
from tasksentry.onboarding import pipeline
from tasksentry.onboarding.llm import ollama_llm

router = APIRouter(prefix="/api/onboard", tags=["Onboarding"])


class OnboardRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    record: str | dict[str, Any]
    tenant_id: str = "default"
    use_llm: bool = False
    model: str = "beam:cloud"
    cloud_opt_in: bool = False
    truth: str | None = None
    flip_prob: float = 0.0
    approve_high_risk: bool = False
    execution_mode: str = "simulation"
    backend_id: str | None = None


@router.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight health response for the web console connection pill."""
    return {"status": "ok", "service": "onboarding"}


def _llm(req: OnboardRequest) -> Any:
    if not req.use_llm:
        return None
    if "cloud" in req.model.lower() and not req.cloud_opt_in:
        raise ValueError("Cloud model use requires explicit per-tenant opt-in.")
    raw_text = req.record if isinstance(req.record, str) else json.dumps(req.record)
    redacted = TenantRedactor(req.tenant_id, redact_ips=True).redact_text(raw_text)
    return ollama_llm(req.model, record_prefix=redacted[:12000])


@router.post("/analyze")
def analyze(req: OnboardRequest) -> dict[str, Any]:
    try:
        return pipeline.analyze(req.record, _llm(req))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/normalize")
def normalize(req: OnboardRequest) -> dict[str, Any]:
    """Convert ordinary JSON into the canonical TaskSentry agent-record format."""
    try:
        return pipeline.normalize(req.record, _llm(req))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/run")
def run(req: OnboardRequest) -> dict[str, Any]:
    try:
        return pipeline.run(
            req.record,
            _llm(req),
            truth=req.truth,
            flip_prob=req.flip_prob,
            approve_high_risk=req.approve_high_risk,
            execution_mode=req.execution_mode,
            backend_id=req.backend_id,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/backends")
def list_backends() -> dict[str, Any]:
    """List explicitly registered live backends without exposing credentials."""
    from tasksentry.harness.backend import default_backend_registry

    return {"backends": default_backend_registry.names()}
