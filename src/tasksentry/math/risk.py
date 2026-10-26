"""Risk-aware remediation gating and rate confidence intervals.

Expected utility of acting:  EU = p*benefit - (1-p)*harm - cost,
with p = P(diagnosis correct) * P(action works | correct).
Policy:
  - system_write / irreversible_write: always human approval.
  - reversible_write: auto-execute only if P(diagnosis) >= min_confidence AND EU > 0 AND the
    diagnosis is unambiguous (conformal set size 1); otherwise ask for approval.
Wilson score interval gives honest uncertainty on success/resolution rates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ALWAYS_APPROVE = frozenset({"system_write", "irreversible_write"})


@dataclass(frozen=True)
class GateDecision:
    auto_execute: bool
    requires_approval: bool
    expected_utility: float
    p_success: float
    reason: str


def expected_utility(p: float, benefit: float, harm: float, cost: float) -> float:
    return p * benefit - (1.0 - p) * harm - cost


def gate_remediation(
    risk: str,
    p_diagnosis: float,
    p_action: float,
    benefit: float,
    harm: float,
    cost: float,
    ambiguous: bool = False,
    min_confidence: float = 0.85,
) -> GateDecision:
    p = p_diagnosis * p_action
    eu = expected_utility(p, benefit, harm, cost)
    if risk in ALWAYS_APPROVE:
        return GateDecision(False, True, eu, p, f"risk tier '{risk}' always needs approval")
    if ambiguous:
        return GateDecision(False, True, eu, p, "diagnosis ambiguous (conformal set > 1)")
    if p_diagnosis < min_confidence:
        return GateDecision(
            False, True, eu, p, f"diagnosis confidence {p_diagnosis:.2f} < {min_confidence:.2f}"
        )
    if eu <= 0.0:
        return GateDecision(False, True, eu, p, "non-positive expected utility")
    return GateDecision(True, False, eu, p, "reversible, confident, positive expected utility")


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
