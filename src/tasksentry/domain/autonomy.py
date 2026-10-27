"""Per-tenant autonomy ladder and promotion policy.

The policy functions consume only trusted catalog metadata and measured harness
state.  Ticket/SOP/log text is never allowed to alter a risk tier or approval
requirement.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.domain.catalog import CommandCatalog
from tasksentry.domain.schema import CommandSpec

AutonomyLevel = Literal["L0", "L1", "L2", "L3"]
DecisionAction = Literal["execute", "propose_only", "require_approval", "deny", "escalate"]
VerifierStatus = Literal["passed", "failed", "unknown", "not_run"]


class AutonomyPolicy(BaseModel):
    """Tenant-scoped policy mapping command classes to autonomy levels."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    levels: dict[str, AutonomyLevel] = Field(default_factory=dict)
    kill_switch: bool = False
    max_actions_per_hour: int = Field(default=100, gt=0)
    max_targets_per_action: int = Field(default=1, gt=0)

    def level_for(self, risk_tier: str) -> AutonomyLevel:
        """Return the configured level, defaulting fail-closed to L3."""
        return self.levels.get(risk_tier, "L3")


class PolicyDecision(BaseModel):
    """Auditable result of one pure autonomy-policy evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    command_id: str
    risk_tier: str
    level: AutonomyLevel
    action: DecisionAction
    reason: str
    requires_verification: bool = False
    rollback_required: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


def decide_action(
    policy: AutonomyPolicy,
    command: CommandSpec | None,
    *,
    verifier_status: VerifierStatus = "not_run",
    budget_ok: bool = True,
    approved: bool = False,
    actions_last_hour: int = 0,
    target_count: int = 1,
) -> PolicyDecision:
    """Pure fail-closed autonomy decision.

    The command's catalog risk is authoritative.  No user-provided text is
    accepted as an input to this function.
    """
    if command is None:
        return PolicyDecision(
            tenant_id=policy.tenant_id,
            command_id="unknown",
            risk_tier="unknown",
            level="L3",
            action="escalate",
            reason="Unknown command cannot be evaluated.",
        )
    level = policy.level_for(command.risk_tier)
    evidence = {
        "verifier_status": verifier_status,
        "budget_ok": budget_ok,
        "approved": approved,
        "actions_last_hour": actions_last_hour,
        "target_count": target_count,
    }
    base: dict[str, Any] = {
        "tenant_id": policy.tenant_id,
        "command_id": command.id,
        "risk_tier": command.risk_tier,
        "level": level,
        "evidence": evidence,
    }
    if policy.kill_switch:
        return PolicyDecision(**base, action="deny", reason="Tenant kill switch is enabled.")
    if actions_last_hour >= policy.max_actions_per_hour:
        return PolicyDecision(**base, action="escalate", reason="Hourly action limit reached.")
    if target_count < 1 or target_count > policy.max_targets_per_action:
        return PolicyDecision(**base, action="escalate", reason="Blast-radius cap exceeded.")
    if not budget_ok:
        return PolicyDecision(**base, action="escalate", reason="Budget is not available.")
    if verifier_status == "failed":
        return PolicyDecision(**base, action="escalate", reason="Required verification failed.")
    if level == "L0":
        return PolicyDecision(**base, action="propose_only", reason="L0 shadow mode.")
    if level == "L3":
        return PolicyDecision(
            **base,
            action="require_approval",
            reason="L3 always requires human approval.",
            requires_verification=True,
        )
    if command.risk_tier == "read":
        return PolicyDecision(**base, action="execute", reason="Read-only action allowed.")
    if level == "L1":
        return PolicyDecision(
            **base,
            action="propose_only",
            reason="L1 executes reads; remediation remains human-controlled.",
        )
    if command.risk_tier == "reversible_write":
        if verifier_status not in {"passed", "not_run"}:
            return PolicyDecision(
                **base, action="escalate", reason="Pre-check verification is required."
            )
        return PolicyDecision(
            **base,
            action="execute",
            reason="L2 permits reversible writes within caps.",
            requires_verification=True,
            rollback_required=True,
        )
    if approved and level == "L2":
        return PolicyDecision(
            **base,
            action="require_approval",
            reason="High-risk command requires approval even under L2.",
            requires_verification=True,
        )
    return PolicyDecision(
        **base,
        action="require_approval",
        reason="This command class is not eligible for automatic execution.",
        requires_verification=True,
    )


@dataclass(frozen=True)
class ShadowProposal:
    """A proposal and optional human disposition recorded in shadow mode."""

    tenant_id: str
    command_id: str
    args: dict[str, Any]
    decision: PolicyDecision
    human_action: str | None = None


class ShadowRecorder:
    """Thread-safe in-memory shadow recorder for receipt integration."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proposals: list[ShadowProposal] = []

    def record(
        self,
        decision: PolicyDecision,
        args: Mapping[str, Any],
        *,
        human_action: str | None = None,
    ) -> ShadowProposal:
        proposal = ShadowProposal(
            tenant_id=decision.tenant_id,
            command_id=decision.command_id,
            args=dict(args),
            decision=decision,
            human_action=human_action,
        )
        with self._lock:
            self._proposals.append(proposal)
        return proposal

    def proposals(self) -> list[ShadowProposal]:
        with self._lock:
            return list(self._proposals)


class ActionRateLimiter:
    """Small tenant-local sliding-window counter used by policy callers."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}

    def count(self, tenant_id: str) -> int:
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(tenant_id, deque())
            while events and events[0] <= now - 3600.0:
                events.popleft()
            return len(events)

    def record(self, tenant_id: str) -> None:
        with self._lock:
            self._events.setdefault(tenant_id, deque()).append(self._clock())


class PromotionCriteria(BaseModel):
    """Minimum evidence required for an autonomy promotion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_samples: int = Field(default=100, ge=1)
    min_success_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0)
    require_zero_unsafe: bool = True
    require_rollback_tested: bool = True


class PromotionEvidence(BaseModel):
    """Measured evidence collected from replay/shadow operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    samples: int = Field(ge=0)
    successes: int = Field(ge=0)
    unsafe_actions: int = Field(default=0, ge=0)
    policy_violations: int = Field(default=0, ge=0)
    rollback_tested: bool = False


class PromotionDecision(BaseModel):
    """Promotion result with confidence bound and blocking reasons."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    can_promote: bool
    lower_bound: float
    sample_size: int
    reasons: list[str] = Field(default_factory=list)


def wilson_lower_bound(successes: int, samples: int, confidence: float = 0.95) -> float:
    """Return the lower Wilson confidence bound for a binomial success rate."""
    if samples <= 0 or successes < 0 or successes > samples:
        raise ValueError("successes must be between 0 and samples, with samples > 0")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    # Deterministic z values for the confidence levels supported by this offline policy.
    z = {0.90: 1.6448536269514722, 0.95: 1.959963984540054, 0.99: 2.5758293035489004}.get(
        confidence
    )
    if z is None:
        raise ValueError("confidence must be one of 0.90, 0.95, or 0.99")
    rate = successes / samples
    denominator = 1.0 + z * z / samples
    centre = rate + z * z / (2.0 * samples)
    spread = z * math.sqrt(rate * (1.0 - rate) / samples + z * z / (4.0 * samples * samples))
    return (centre - spread) / denominator


def can_promote(
    evidence: PromotionEvidence,
    criteria: PromotionCriteria | None = None,
) -> PromotionDecision:
    """Check promotion gates without allowing small-N or unsafe promotion."""
    criteria = criteria or PromotionCriteria()
    lower = (
        wilson_lower_bound(evidence.successes, evidence.samples, criteria.confidence)
        if evidence.samples
        else 0.0
    )
    reasons: list[str] = []
    if evidence.samples < criteria.min_samples:
        reasons.append(f"insufficient samples: {evidence.samples} < {criteria.min_samples}")
    if lower < criteria.min_success_rate:
        reasons.append(f"lower confidence bound {lower:.4f} < {criteria.min_success_rate:.4f}")
    if evidence.policy_violations:
        reasons.append("policy violations are non-zero")
    if criteria.require_zero_unsafe and evidence.unsafe_actions:
        reasons.append("unsafe actions are non-zero")
    if criteria.require_rollback_tested and not evidence.rollback_tested:
        reasons.append("rollback has not been tested")
    return PromotionDecision(
        can_promote=not reasons,
        lower_bound=lower,
        sample_size=evidence.samples,
        reasons=reasons,
    )


def make_catalog_policy_callback(
    catalog: CommandCatalog,
    policy: AutonomyPolicy,
    *,
    verifier_status: VerifierStatus = "not_run",
    budget_ok: bool = True,
    actions_last_hour: int = 0,
    target_count: int = 1,
) -> Callable[[str, str, Mapping[str, Any]], PolicyDecision]:
    """Adapt catalog metadata to the optional ``ToolGovernor`` autonomy callback."""

    def callback(command_id: str, _risk_tier: str, _args: Mapping[str, Any]) -> PolicyDecision:
        command = None
        try:
            command = catalog.command(command_id)
        except ValueError:
            command = None
        return decide_action(
            policy,
            command,
            verifier_status=verifier_status,
            budget_ok=budget_ok,
            actions_last_hour=actions_last_hour,
            target_count=target_count,
        )

    return callback
