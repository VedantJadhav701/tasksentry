"""REST endpoints for universal onboarding. Mount with app.include_router(router)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from tasksentry.onboarding import pipeline
from tasksentry.onboarding.llm import ollama_llm

router = APIRouter(prefix="/api/onboard", tags=["Onboarding"])


class OnboardRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    record: str
    use_llm: bool = True
    model: str = "beam:cloud"
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
    return ollama_llm(req.model) if req.use_llm else None


@router.post("/analyze")
def analyze(req: OnboardRequest) -> dict[str, Any]:
    try:
        return pipeline.analyze(req.record, _llm(req))
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
