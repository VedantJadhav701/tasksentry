"""Sequential tests for verification and drift detection.

SPRT (Wald): H1 = "healthy" (per-read success prob p1) vs H0 = "not healthy" (p0).
Log-likelihood ratio accumulates per observation; stop when it crosses
    A = ln((1-beta)/alpha)  -> accept H1
    B = ln(beta/(1-alpha))  -> accept H0
This decides with bounded error rates using the fewest reads.

CUSUM: one-sided change detector, S_t = max(0, S_{t-1} + x_t - k); alarm if S_t > h.
"""

from __future__ import annotations

import math


class SPRT:
    def __init__(self, p0: float = 0.5, p1: float = 0.95, alpha: float = 0.05, beta: float = 0.05):
        if not 0.0 < p0 < p1 < 1.0:
            raise ValueError("require 0 < p0 < p1 < 1")
        self.upper = math.log((1.0 - beta) / alpha)
        self.lower = math.log(beta / (1.0 - alpha))
        self._pos = math.log(p1 / p0)
        self._neg = math.log((1.0 - p1) / (1.0 - p0))
        self.llr = 0.0
        self.n = 0

    def update(self, success: bool) -> str:
        self.llr += self._pos if success else self._neg
        self.n += 1
        if self.llr >= self.upper:
            return "accept_h1"
        if self.llr <= self.lower:
            return "accept_h0"
        return "continue"


class CUSUM:
    def __init__(self, k: float, h: float) -> None:
        self.k = k
        self.h = h
        self.s = 0.0

    def update(self, x: float) -> bool:
        self.s = max(0.0, self.s + x - self.k)
        return self.s > self.h
