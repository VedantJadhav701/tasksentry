"""Split conformal prediction for root-cause label sets.

Nonconformity score s(x, y) = 1 - P(y | x). With n calibration pairs and level
alpha, q_hat is the ceil((n+1)(1-alpha))/n empirical quantile of the scores.
Prediction set C(x) = {h : 1 - P(h | x) <= q_hat} satisfies, under
exchangeability, P(y_true in C(x)) >= 1 - alpha (finite-sample guarantee).

Operational use: |C| == 1 -> confident; |C| > 1 -> ambiguous, require approval
or escalate; the guarantee only holds if calibration data resembles production
data, so calibrate on held-out labelled tickets, not on simulator output alone.
"""

from __future__ import annotations

import math


def conformal_quantile(scores: list[float], alpha: float) -> float:
    n = len(scores)
    if n == 0:
        return math.inf
    k = math.ceil((n + 1) * (1.0 - alpha))
    if k > n:
        return math.inf
    return sorted(scores)[k - 1]


class SplitConformal:
    def __init__(self, alpha: float = 0.1) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        self.alpha = alpha
        self.q_hat: float = math.inf
        self.n_calibration = 0

    def fit(self, calibration: list[tuple[dict[str, float], str]]) -> SplitConformal:
        scores = [1.0 - probs.get(truth, 0.0) for probs, truth in calibration]
        self.q_hat = conformal_quantile(scores, self.alpha)
        self.n_calibration = len(scores)
        return self

    def predict_set(self, probs: dict[str, float]) -> list[str]:
        members = [h for h, p in probs.items() if 1.0 - p <= self.q_hat]
        return sorted(members, key=lambda h: -probs[h])

    def coverage(self, test: list[tuple[dict[str, float], str]]) -> float:
        if not test:
            return 0.0
        hit = sum(1 for probs, truth in test if truth in self.predict_set(probs))
        return hit / len(test)
