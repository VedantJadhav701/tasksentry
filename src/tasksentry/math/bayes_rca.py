"""Bayesian root-cause inference with information-gain probe selection.

Model
-----
Hypotheses H = {h_1..h_k} with prior P(h). Each probe p returns a binary outcome
o in {abnormal, normal} with sensitivity s_p(h) = P(abnormal | h).

Posterior update (conditionally independent probes):
    P(h | o_1..o_t)  proportional to  P(h) * prod_i P(o_i | h)

Next probe is chosen by expected information gain per unit cost:
    EIG(p) = H[P(h)] - E_o[ H[P(h | o)] ]          (bits)
    p*     = argmax_p EIG(p) / cost(p)

Model pooling (domain-trained LLM as a second expert), log-linear pooling:
    P_pool(h)  proportional to  P_bayes(h)^(1-w) * P_model(h)^w
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

_EPS = 1e-6


def normalize(p: dict[str, float]) -> dict[str, float]:
    total = sum(p.values())
    if total <= 0.0:
        n = len(p)
        return dict.fromkeys(p, 1.0 / n) if n else {}
    return {k: v / total for k, v in p.items()}


def entropy(p: dict[str, float]) -> float:
    """Shannon entropy in bits."""
    return -sum(v * math.log2(v) for v in p.values() if v > 0.0)


def kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """KL(p || q) in bits; q is floored to avoid infinities."""
    return sum(v * math.log2(v / max(q.get(k, 0.0), _EPS)) for k, v in p.items() if v > 0.0)


def dirichlet_prior(
    counts: dict[str, int], hypotheses: Iterable[str], alpha: float = 1.0
) -> dict[str, float]:
    """Posterior-mean of a symmetric Dirichlet(alpha) prior given observed class counts."""
    hyps = list(hypotheses)
    total = sum(counts.get(h, 0) for h in hyps) + alpha * len(hyps)
    return {h: (counts.get(h, 0) + alpha) / total for h in hyps}


def pool_with_model(
    posterior: dict[str, float], model_probs: dict[str, float], weight: float
) -> dict[str, float]:
    """Log-linear opinion pool of the Bayesian posterior and a trained-model distribution."""
    w = min(max(weight, 0.0), 1.0)
    out = {
        h: (max(p, _EPS) ** (1.0 - w)) * (max(model_probs.get(h, 0.0), _EPS) ** w)
        for h, p in posterior.items()
    }
    return normalize(out)


@dataclass(frozen=True)
class Probe:
    """A diagnostic probe with per-hypothesis P(abnormal | h) and an execution cost."""

    name: str
    sensitivity: dict[str, float]
    cost: float = 1.0


@dataclass
class BayesRCA:
    priors: dict[str, float]
    probes: list[Probe]
    posterior: dict[str, float] = field(init=False)
    observed: dict[str, bool] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.priors = normalize(self.priors)
        self.posterior = dict(self.priors)
        self._probes = {p.name: p for p in self.probes}

    @staticmethod
    def _lik(probe: Probe, abnormal: bool, h: str) -> float:
        s = min(max(probe.sensitivity.get(h, 0.5), _EPS), 1.0 - _EPS)
        return s if abnormal else 1.0 - s

    def update(self, name: str, abnormal: bool) -> dict[str, float]:
        probe = self._probes[name]
        self.posterior = normalize(
            {h: p * self._lik(probe, abnormal, h) for h, p in self.posterior.items()}
        )
        self.observed[name] = abnormal
        return self.posterior

    def expected_information_gain(self, name: str) -> float:
        probe = self._probes[name]
        h0 = entropy(self.posterior)
        expected_h = 0.0
        for ab in (True, False):
            joint = {h: p * self._lik(probe, ab, h) for h, p in self.posterior.items()}
            pa = sum(joint.values())
            if pa > 0.0:
                expected_h += pa * entropy({h: v / pa for h, v in joint.items()})
        return max(h0 - expected_h, 0.0)

    def next_probe(self, min_gain_per_cost: float = 1e-3) -> str | None:
        best: tuple[float, str] | None = None
        for name, probe in self._probes.items():
            if name in self.observed:
                continue
            score = self.expected_information_gain(name) / max(probe.cost, _EPS)
            if best is None or score > best[0]:
                best = (score, name)
        if best is None or best[0] < min_gain_per_cost:
            return None
        return best[1]

    def map_hypothesis(self) -> tuple[str, float]:
        h = max(self.posterior, key=lambda k: self.posterior[k])
        return h, self.posterior[h]
