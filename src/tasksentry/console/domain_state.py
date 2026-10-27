"""In-process domain governance state used by the local Console review panel."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.domain.autonomy import AutonomyPolicy


class ReviewItem(BaseModel):
    """A generated hypothesis/probe/remediation awaiting human review."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: f"review_{uuid.uuid4().hex[:8]}")
    tenant_id: str
    kind: Literal["hypothesis", "probe", "remediation"]
    name: str
    risk_tier: str = "read"
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "approved", "rejected"] = "pending"
    decision_note: str | None = None


class ProposalItem(BaseModel):
    """A shadow proposal and the human action eventually taken."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=lambda: f"proposal_{uuid.uuid4().hex[:8]}")
    tenant_id: str
    command_id: str
    risk_tier: str
    args: dict[str, Any] = Field(default_factory=dict)
    action: str = "propose_only"
    human_action: str | None = None


class DomainState:
    """Thread-safe local state; execution is never triggered by review writes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._policies: dict[str, AutonomyPolicy] = {}
        self._reviews: dict[str, ReviewItem] = {}
        self._proposals: dict[str, ProposalItem] = {}

    def policy(self, tenant_id: str) -> AutonomyPolicy:
        with self._lock:
            return self._policies.setdefault(
                tenant_id,
                AutonomyPolicy(
                    tenant_id=tenant_id,
                    levels={
                        "read": "L0",
                        "reversible_write": "L0",
                        "system_write": "L3",
                        "destructive": "L3",
                    },
                ),
            )

    def update_policy(self, policy: AutonomyPolicy) -> AutonomyPolicy:
        with self._lock:
            self._policies[policy.tenant_id] = policy
            return policy

    def add_review(self, item: ReviewItem) -> ReviewItem:
        with self._lock:
            self._reviews[item.review_id] = item
            return item

    def reviews(self, tenant_id: str) -> list[ReviewItem]:
        with self._lock:
            return [item for item in self._reviews.values() if item.tenant_id == tenant_id]

    def decide_review(self, review_id: str, approved: bool, note: str | None) -> ReviewItem | None:
        with self._lock:
            item = self._reviews.get(review_id)
            if item is None:
                return None
            item.status = "approved" if approved else "rejected"
            item.decision_note = note
            return item

    def add_proposal(self, item: ProposalItem) -> ProposalItem:
        with self._lock:
            self._proposals[item.proposal_id] = item
            return item

    def proposals(self, tenant_id: str) -> list[ProposalItem]:
        with self._lock:
            return [item for item in self._proposals.values() if item.tenant_id == tenant_id]


default_domain_state = DomainState()
