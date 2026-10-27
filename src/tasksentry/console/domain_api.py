"""Small REST surface for the Console's autonomy and harness-review panel."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from tasksentry.console.approvals import default_approval_manager
from tasksentry.console.domain_state import (
    ProposalItem,
    ReviewItem,
    default_domain_state,
)
from tasksentry.domain.autonomy import AutonomyLevel

router = APIRouter(prefix="/api/domain", tags=["Domain governance"])


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    levels: dict[str, AutonomyLevel] | None = None
    kill_switch: bool | None = None
    max_actions_per_hour: int | None = Field(default=None, gt=0)
    max_targets_per_action: int | None = Field(default=None, gt=0)


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)


@router.get("/autonomy")
def get_autonomy(tenant_id: str = "default") -> dict[str, Any]:
    policy = default_domain_state.policy(tenant_id)
    return {
        "tenant_id": tenant_id,
        "policy": policy.model_dump(mode="json"),
        "pending_approvals": [
            request.model_dump(mode="json") for request in default_approval_manager.list_pending()
        ],
        "kill_switch": policy.kill_switch,
    }


@router.put("/autonomy")
def update_autonomy(request: PolicyUpdate) -> dict[str, Any]:
    current = default_domain_state.policy(request.tenant_id)
    updated = current.model_copy(
        update={
            key: value
            for key, value in {
                "levels": request.levels,
                "kill_switch": request.kill_switch,
                "max_actions_per_hour": request.max_actions_per_hour,
                "max_targets_per_action": request.max_targets_per_action,
            }.items()
            if value is not None
        }
    )
    return {
        "tenant_id": request.tenant_id,
        "policy": default_domain_state.update_policy(updated).model_dump(mode="json"),
    }


@router.post("/autonomy/kill-switch")
def set_kill_switch(tenant_id: str, enabled: bool = True) -> dict[str, Any]:
    current = default_domain_state.policy(tenant_id)
    updated = default_domain_state.update_policy(
        current.model_copy(update={"kill_switch": enabled})
    )
    return {"tenant_id": tenant_id, "kill_switch": updated.kill_switch}


@router.get("/reviews")
def list_reviews(tenant_id: str = "default") -> dict[str, Any]:
    items = default_domain_state.reviews(tenant_id)
    return {"tenant_id": tenant_id, "reviews": [item.model_dump(mode="json") for item in items]}


@router.post("/reviews", status_code=201)
def create_review(item: ReviewItem) -> dict[str, Any]:
    return default_domain_state.add_review(item).model_dump(mode="json")


@router.post("/reviews/{review_id}/approve")
def approve_review(review_id: str, decision: ReviewDecision | None = None) -> dict[str, Any]:
    item = default_domain_state.decide_review(review_id, True, decision.note if decision else None)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return item.model_dump(mode="json")


@router.post("/reviews/{review_id}/reject")
def reject_review(review_id: str, decision: ReviewDecision | None = None) -> dict[str, Any]:
    item = default_domain_state.decide_review(review_id, False, decision.note if decision else None)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    return item.model_dump(mode="json")


@router.get("/proposals")
def list_proposals(tenant_id: str = "default") -> dict[str, Any]:
    items = default_domain_state.proposals(tenant_id)
    return {"tenant_id": tenant_id, "proposals": [item.model_dump(mode="json") for item in items]}


@router.post("/proposals", status_code=201)
def create_proposal(item: ProposalItem) -> dict[str, Any]:
    return default_domain_state.add_proposal(item).model_dump(mode="json")
