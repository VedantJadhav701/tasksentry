"""Cost-aware Thompson sampling for model-lane selection.

Each arm (model) keeps a Beta(a, b) posterior over its reward in [0, 1].
select(): sample theta_i ~ Beta(a_i, b_i), pick argmax.
update(arm, r): a += r, b += 1 - r (fractional rewards allowed).
An optional discount gamma < 1 shrinks old evidence so the policy adapts when a
model degrades or improves (non-stationary environments).
"""

from __future__ import annotations

import random


def lane_reward(
    success: bool,
    latency_s: float,
    cost_usd: float,
    lat_weight: float = 0.02,
    cost_weight: float = 1.0,
) -> float:
    """Scalar reward in [0, 1]: success minus latency and cost penalties."""
    r = (1.0 if success else 0.0) - lat_weight * latency_s - cost_weight * cost_usd
    return min(max(r, 0.0), 1.0)


class ThompsonSelector:
    def __init__(self, arms: list[str], seed: int | None = None, discount: float = 1.0) -> None:
        self.params: dict[str, list[float]] = {a: [1.0, 1.0] for a in arms}
        self.rng = random.Random(seed)
        self.discount = discount

    def select(self) -> str:
        draws = {a: self.rng.betavariate(ab[0], ab[1]) for a, ab in self.params.items()}
        return max(draws, key=lambda k: draws[k])

    def update(self, arm: str, reward: float) -> None:
        r = min(max(reward, 0.0), 1.0)
        if self.discount < 1.0:
            for ab in self.params.values():
                ab[0] = 1.0 + (ab[0] - 1.0) * self.discount
                ab[1] = 1.0 + (ab[1] - 1.0) * self.discount
        self.params[arm][0] += r
        self.params[arm][1] += 1.0 - r

    def mean(self, arm: str) -> float:
        a, b = self.params[arm]
        return a / (a + b)
