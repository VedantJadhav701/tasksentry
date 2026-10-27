"""M4 autonomy ladder, shadow, limits, promotion, and governor integration tests."""

from __future__ import annotations

import pytest

from tasksentry.domain.autonomy import (
    ActionRateLimiter,
    AutonomyPolicy,
    PromotionCriteria,
    PromotionEvidence,
    ShadowRecorder,
    can_promote,
    decide_action,
    wilson_lower_bound,
)
from tasksentry.domain.catalog import CommandCatalog
from tasksentry.domain.schema import CommandSpec
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import Tool, ToolRegistry


def _command(risk: str = "read") -> CommandSpec:
    return CommandSpec(
        tenant_id="acme",
        tenant_scope="acme",
        id=f"{risk}_command",
        template=("probe",),
        argument_schema={"type": "object", "properties": {}},
        risk_tier=risk,  # type: ignore[arg-type]
    )


def _policy(**levels: str) -> AutonomyPolicy:
    return AutonomyPolicy(tenant_id="acme", levels=levels)  # type: ignore[arg-type]


def test_l0_is_shadow_propose_only() -> None:
    result = decide_action(_policy(read="L0"), _command())
    assert result.action == "propose_only"


@pytest.mark.parametrize("risk", ["read", "reversible_write", "system_write", "destructive"])
def test_l3_never_executes(risk: str) -> None:
    result = decide_action(_policy(**{risk: "L3"}), _command(risk))
    assert result.action == "require_approval"
    assert result.action != "execute"


def test_l1_executes_only_read() -> None:
    assert decide_action(_policy(read="L1"), _command()).action == "execute"
    assert (
        decide_action(_policy(reversible_write="L1"), _command("reversible_write")).action
        == "propose_only"
    )


def test_l2_executes_reversible_write_after_precheck() -> None:
    result = decide_action(
        _policy(reversible_write="L2"), _command("reversible_write"), verifier_status="passed"
    )
    assert result.action == "execute" and result.rollback_required is True


def test_l2_high_risk_write_requires_approval() -> None:
    result = decide_action(_policy(system_write="L2"), _command("system_write"))
    assert result.action == "require_approval"


def test_unknown_command_escalates() -> None:
    assert decide_action(_policy(), None).action == "escalate"


def test_kill_switch_denies_everything() -> None:
    policy = AutonomyPolicy(tenant_id="acme", kill_switch=True, levels={"read": "L1"})
    assert decide_action(policy, _command()).action == "deny"


def test_budget_failure_escalates() -> None:
    assert decide_action(_policy(read="L1"), _command(), budget_ok=False).action == "escalate"


def test_verification_failure_escalates() -> None:
    assert (
        decide_action(_policy(read="L1"), _command(), verifier_status="failed").action == "escalate"
    )


def test_rate_limit_escalates() -> None:
    policy = AutonomyPolicy(tenant_id="acme", levels={"read": "L1"}, max_actions_per_hour=2)
    assert decide_action(policy, _command(), actions_last_hour=2).action == "escalate"


def test_blast_radius_escalates() -> None:
    policy = AutonomyPolicy(tenant_id="acme", levels={"read": "L1"}, max_targets_per_action=1)
    assert decide_action(policy, _command(), target_count=2).action == "escalate"


def test_shadow_recorder_preserves_proposal_and_human_action() -> None:
    recorder = ShadowRecorder()
    decision = decide_action(_policy(read="L0"), _command())
    proposal = recorder.record(decision, {"host": "du-1"}, human_action="rejected")
    assert proposal.human_action == "rejected"
    assert recorder.proposals()[0].args == {"host": "du-1"}


def test_rate_limiter_expires_events() -> None:
    now = [1000.0]
    limiter = ActionRateLimiter(clock=lambda: now[0])
    limiter.record("acme")
    assert limiter.count("acme") == 1
    now[0] += 3601.0
    assert limiter.count("acme") == 0


def test_wilson_bound_is_below_observed_rate() -> None:
    assert 0.0 < wilson_lower_bound(95, 100) < 0.95


def test_wilson_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        wilson_lower_bound(2, 1)


def test_promotion_rejects_small_sample() -> None:
    result = can_promote(PromotionEvidence(samples=10, successes=10, rollback_tested=True))
    assert result.can_promote is False
    assert any("insufficient" in reason for reason in result.reasons)


def test_promotion_rejects_unsafe_actions() -> None:
    criteria = PromotionCriteria(min_samples=10, min_success_rate=0.5)
    result = can_promote(
        PromotionEvidence(samples=10, successes=10, unsafe_actions=1, rollback_tested=True),
        criteria,
    )
    assert result.can_promote is False


def test_promotion_requires_rollback_evidence() -> None:
    criteria = PromotionCriteria(min_samples=10, min_success_rate=0.5)
    result = can_promote(PromotionEvidence(samples=10, successes=10), criteria)
    assert result.can_promote is False
    assert any("rollback" in reason for reason in result.reasons)


def test_promotion_passes_with_sufficient_clean_evidence() -> None:
    criteria = PromotionCriteria(min_samples=100, min_success_rate=0.9)
    result = can_promote(
        PromotionEvidence(samples=100, successes=100, rollback_tested=True), criteria
    )
    assert result.can_promote is True


def test_governor_blocks_autonomy_proposal_before_execution() -> None:
    calls: list[str] = []
    from pydantic import BaseModel

    # Use a real Pydantic model while keeping the test focused on the callback.
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="read_command",
            input_model=BaseModel,
            callable=lambda: calls.append("ran") or {"ok": True},
            risk="read",
        )
    )
    result = ToolGovernor(
        registry,
        autonomy_decider=lambda *_: {"action": "propose_only"},
    ).execute("read_command", {})
    assert result["reason"] == "autonomy_propose_only"
    assert calls == []


def test_governor_preserves_l3_approval_callback() -> None:
    from pydantic import BaseModel

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="system_command",
            input_model=BaseModel,
            callable=lambda: {"ok": True},
            risk="system_write",
        )
    )
    result = ToolGovernor(
        registry,
        autonomy_decider=lambda *_: {"action": "require_approval"},
        write_approval_callback=lambda *_: True,
    ).execute("system_command", {})
    assert result["status"] == "success"


def test_catalog_risk_is_used_by_policy_callback() -> None:
    command = _command("system_write")
    catalog = CommandCatalog(tenant_id="acme", version="v1", commands=(command,))
    from tasksentry.domain.autonomy import make_catalog_policy_callback

    callback = make_catalog_policy_callback(catalog, _policy(system_write="L3"))
    assert callback(command.id, "read", {}).action == "require_approval"
