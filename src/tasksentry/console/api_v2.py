"""Extra console endpoints: Bayesian diagnose + analytics.

Wire into your app next to the existing router:
    from tasksentry.console.api_v2 import router as router_v2
    app.include_router(router_v2)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/chat/telecom", tags=["Telecom-v2"])


class DiagnoseRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticket_id: str
    flip_prob: float = 0.0
    approve_high_risk: bool = False  # demo switch; real UI should use the approval manager


@router.post("/diagnose")
def diagnose(req: DiagnoseRequest) -> dict[str, Any]:
    """Bayesian + conformal diagnosis, gated remediation, SPRT verification, signed chain."""
    from tasksentry.harness.engine import UniversalEngine
    from tasksentry.telecom.loader import resolve_or_create_ticket
    from tasksentry.telecom.pack import build_from_state
    from tasksentry.telecom.tools import TelecomSimulationState

    ticket = resolve_or_create_ticket(req.ticket_id)
    state = TelecomSimulationState.from_ticket_failure_type(ticket.metadata.failure_type)
    pack = build_from_state(state, flip_prob=req.flip_prob)
    engine = UniversalEngine(pack, approver=(lambda *_: True) if req.approve_high_risk else None)
    out = engine.solve().to_dict()
    out["ticket_id"] = ticket.id
    return out


@router.get("/analytics")
def analytics(limit: int = 200) -> dict[str, Any]:
    """Failure distribution + estimated priors over the first `limit` dataset tickets."""
    from collections import Counter

    from tasksentry.telecom.analytics import estimate_priors
    from tasksentry.telecom.loader import load_tickets
    from tasksentry.telecom.pack import hypothesis_of_failure

    tickets = load_tickets(limit=limit)
    dist = Counter(hypothesis_of_failure(t.metadata.failure_type) or "unmapped" for t in tickets)
    return {
        "tickets": len(tickets),
        "distribution": dict(dist),
        "estimated_priors": estimate_priors(tickets),
    }
