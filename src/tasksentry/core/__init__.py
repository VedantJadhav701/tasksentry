"""Core task model: canonical state and task contract."""

from tasksentry.core.contract import (
    VERIFIER_NAMES,
    BudgetLimits,
    HypothesisSpec,
    Milestone,
    SafetyRules,
    SuccessCriterion,
    TaskContract,
    VerifierSpec,
)
from tasksentry.core.state import (
    CanonicalState,
    action_fingerprint,
    build_coding_world,
    canonical_json,
    canonical_state_hash,
    canonicalize,
    normalize_diff,
    snapshot_from_state,
)

__all__ = [
    "VERIFIER_NAMES",
    "BudgetLimits",
    "CanonicalState",
    "HypothesisSpec",
    "Milestone",
    "SafetyRules",
    "SuccessCriterion",
    "TaskContract",
    "VerifierSpec",
    "action_fingerprint",
    "build_coding_world",
    "canonical_json",
    "canonical_state_hash",
    "canonicalize",
    "normalize_diff",
    "snapshot_from_state",
]
