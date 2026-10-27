"""Canonical, provider-neutral domain trajectory schema.

The schema mirrors the trajectory contract in ``plan.md``.  Domain text and
observations are data, not policy: risk tiers and execution permissions belong
to the command catalog and autonomy policy modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1"
LabelSource = Literal["human_confirmed", "auto_verified", "inferred"]
RiskTier = Literal["read", "reversible_write", "system_write", "destructive"]


class DomainModel(BaseModel):
    """Common immutable model settings for customer-domain records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default=SCHEMA_VERSION, min_length=1)
    tenant_id: str = Field(min_length=1, max_length=200)
    label_source: LabelSource = "inferred"

    @field_validator("tenant_id")
    @classmethod
    def _tenant_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tenant_id must not be blank")
        return value


class Ticket(DomainModel):
    """A normalized support ticket with untrusted customer text."""

    id: str = Field(min_length=1, max_length=300)
    category: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    customer_id: str | None = None
    created_at: datetime | None = None


class SopDoc(DomainModel):
    """A versioned SOP document and its ordered troubleshooting steps."""

    id: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=100)
    title: str = ""
    text: str = ""
    steps: list[Step] = Field(default_factory=list)


class CommandSpec(DomainModel):
    """A catalog-neutral command reference used by trajectory actions.

    Full executable command policy is defined by ``domain.catalog``.  Keeping
    this reference typed prevents a model from emitting free-form shell text in
    a trajectory.
    """

    id: str = Field(min_length=1, max_length=200)
    description: str = ""
    template: tuple[str, ...] = Field(default_factory=tuple)
    argument_schema: dict[str, Any] = Field(default_factory=dict)
    preconditions: tuple[str, ...] = Field(default_factory=tuple)
    verifier_reference: str | None = None
    rollback_command_id: str | None = None
    tenant_scope: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    risk_tier: RiskTier = "read"


class Step(DomainModel):
    """One observed SOP/action step in a trajectory."""

    i: int = Field(ge=1)
    thought_summary: str = ""
    action: CommandSpec
    observation: dict[str, Any] = Field(default_factory=dict)
    posterior: dict[str, float] = Field(default_factory=dict)

    @field_validator("posterior")
    @classmethod
    def _posterior_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        if any(prob < 0.0 or prob > 1.0 for prob in value.values()):
            raise ValueError("posterior probabilities must be between 0 and 1")
        return value


class Outcome(DomainModel):
    """Verified or escalated result of a ticket trajectory."""

    resolved: bool = False
    verification: dict[str, Any] = Field(default_factory=dict)
    escalation_reason: str | None = None


class Trajectory(DomainModel):
    """Canonical training/evaluation record produced by the harness."""

    ticket: Ticket
    context: dict[str, Any] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    decision: dict[str, Any] = Field(default_factory=dict)
    remediation: dict[str, Any] | None = None
    outcome: Outcome
