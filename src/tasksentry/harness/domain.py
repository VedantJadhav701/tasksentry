"""Domain pack: everything the universal engine needs to work in a new domain.

To port the harness to another domain (power grid, cloud SRE, medical triage,
oil & gas...), supply: hypotheses + priors, probes with sensitivities,
a probe runner, a health check, remediations with risk tiers, and escalation
teams. A domain-trained model plugs in through `brain` on the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tasksentry.math.bayes_rca import Probe


@dataclass(frozen=True)
class Remediation:
    name: str
    risk: str  # reversible_write | system_write | irreversible_write
    run: Callable[[], dict[str, Any]]
    success_prob: float = 0.9
    benefit: float = 100.0
    harm: float = 20.0
    cost: float = 1.0


@dataclass
class DomainPack:
    name: str
    priors: dict[str, float]
    probes: list[Probe]
    run_probe: Callable[[str], bool]  # True = abnormal
    verify: Callable[[], bool]  # True = healthy reading
    remediations: dict[str, Remediation] = field(default_factory=dict)
    escalation: dict[str, str] = field(default_factory=dict)
    default_escalation: str = "Specialist team"
