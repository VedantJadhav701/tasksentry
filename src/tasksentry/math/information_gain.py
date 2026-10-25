"""Estimated information gain for the Agent Progress Gain (APG) formula.

Two estimators are provided.

1. :class:`HypothesisBeliefTracker` (a real estimator)
   The task contract defines a hypothesis set ``H = {h_1, ..., h_k}`` with prior
   probabilities ``P(h)``. A :class:`LikelihoodModel` supplies ``P(o | h)``. Each
   observation updates the belief by Bayes' rule::

       P(h | o) = P(o | h) P(h) / sum_j P(o | j) P(j)

   Shannon entropy (in bits) of a distribution ``P``::

       H(P) = - sum_i p_i log2(p_i)          (with 0 log 0 := 0)

   and the information gain of step ``t`` is the entropy reduction::

       IG_t = H(P_t) - H(P_{t+1})

   Note: the *expected* gain is never negative (it is a mutual information),
   but the *realized* gain of one surprising observation can be negative.

2. :class:`ProxyInformationGain` (a PROXY, used when no hypotheses are configured)
   Defined relative to the initial snapshot ``0``::

       Proxy(s) = max(0, open_0 - open_s) / max(open_0, 1)
                + max(0, passed_s - passed_0) / max(passed_0, 1)
                + max(0, done_s - done_0) / max(done_0, 1)

   The per-step value is ``Proxy(current) - Proxy(previous)``, so the per-step
   values telescope to the cumulative proxy. THIS IS NOT MUTUAL INFORMATION. It
   is a bounded heuristic that rewards fewer open failures, more passed checks,
   and more completed milestones; it carries no probabilistic meaning.
"""

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from tasksentry.exceptions import InformationGainError
from tasksentry.math.similarity import normalize_volatile

PROXY_LABEL = "PROXY: not mutual information; heuristic progress signal"
_SUM_TOLERANCE = 1e-6


def entropy(probabilities: Iterable[float]) -> float:
    """Return the Shannon entropy in bits, ``-sum p log2 p`` (``0 log 0 = 0``).

    Raises:
        InformationGainError: if any probability is negative or not finite.
    """
    total = 0.0
    for p in probabilities:
        if not math.isfinite(p) or p < 0.0:
            raise InformationGainError(f"invalid probability: {p!r}")
        if p > 0.0:
            total -= p * math.log2(p)
    return max(0.0, total)


@runtime_checkable
class LikelihoodModel(Protocol):
    """Protocol supplying ``P(o | h)`` for belief updates."""

    def likelihood(self, observation: str, hypothesis: str) -> float:
        """Return the non-negative likelihood of ``observation`` under ``hypothesis``."""
        ...


def _observation_key(observation: str) -> str:
    return normalize_volatile(observation).lower()


class TableLikelihoodModel:
    """A lookup-table :class:`LikelihoodModel`.

    Args:
        table: ``{observation: {hypothesis: P(observation | hypothesis)}}``.
            Observations are matched after volatile-field normalization and
            lowercasing.
        default: likelihood returned for an observation or hypothesis missing
            from the table. The default of 1.0 makes unknown observations
            uninformative (the posterior equals the prior).

    Raises:
        InformationGainError: if any likelihood is negative or not finite.
    """

    def __init__(
        self,
        table: Mapping[str, Mapping[str, float]],
        default: float = 1.0,
    ) -> None:
        _check_likelihood(default)
        self._default = default
        self._table: dict[str, dict[str, float]] = {}
        for observation, row in table.items():
            for value in row.values():
                _check_likelihood(value)
            self._table[_observation_key(observation)] = dict(row)

    def likelihood(self, observation: str, hypothesis: str) -> float:
        """Return ``P(observation | hypothesis)`` from the table, or the default."""
        row = self._table.get(_observation_key(observation))
        if row is None:
            return self._default
        return row.get(hypothesis, self._default)


def _check_likelihood(value: float) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise InformationGainError(f"invalid likelihood: {value!r}")


@dataclass(frozen=True)
class BeliefUpdate:
    """The result of one Bayesian belief update."""

    observation: str
    prior: dict[str, float]
    posterior: dict[str, float]
    entropy_before: float
    entropy_after: float
    gain_bits: float
    normalized_gain: float


class HypothesisBeliefTracker:
    """Bayesian belief over a hypothesis set with entropy-based information gain.

    Args:
        priors: ``{hypothesis: P(h)}``. Must contain at least one hypothesis and
            sum to 1 within 1e-6 unless ``normalize_priors`` is true.
        likelihood: model supplying ``P(o | h)``.
        normalize_priors: rescale priors to sum to 1 instead of rejecting them.

    Raises:
        InformationGainError: for empty, negative, non-finite, or mis-summed priors.
    """

    def __init__(
        self,
        priors: Mapping[str, float],
        likelihood: LikelihoodModel,
        *,
        normalize_priors: bool = False,
    ) -> None:
        if not priors:
            raise InformationGainError("at least one hypothesis is required")
        for name, p in priors.items():
            if not math.isfinite(p) or p < 0.0:
                raise InformationGainError(f"invalid prior for {name!r}: {p!r}")
        total = sum(priors.values())
        if total <= 0.0:
            raise InformationGainError("priors must have a positive sum")
        if abs(total - 1.0) > _SUM_TOLERANCE:
            if not normalize_priors:
                raise InformationGainError(f"priors must sum to 1, got {total!r}")
            priors = {name: p / total for name, p in priors.items()}
        self._initial: dict[str, float] = dict(priors)
        self._beliefs: dict[str, float] = dict(priors)
        self._likelihood = likelihood

    @property
    def beliefs(self) -> dict[str, float]:
        """A copy of the current belief distribution ``P_t``."""
        return dict(self._beliefs)

    @property
    def entropy(self) -> float:
        """Entropy ``H(P_t)`` of the current belief, in bits."""
        return entropy(self._beliefs.values())

    @property
    def max_entropy(self) -> float:
        """Maximum possible entropy ``log2(k)`` for ``k`` hypotheses."""
        return math.log2(len(self._beliefs))

    def most_likely(self) -> tuple[str, float]:
        """Return the hypothesis with the highest posterior and its probability."""
        name = max(self._beliefs, key=lambda h: self._beliefs[h])
        return name, self._beliefs[name]

    def reset(self) -> None:
        """Restore the belief to the initial priors."""
        self._beliefs = dict(self._initial)

    def update(self, observation: str) -> BeliefUpdate:
        """Apply Bayes' rule for one observation and return the gain.

        Raises:
            InformationGainError: if the observation has zero total probability
                under every hypothesis, or a likelihood is invalid.
        """
        prior = dict(self._beliefs)
        weights: dict[str, float] = {}
        for hypothesis, p in prior.items():
            like = self._likelihood.likelihood(observation, hypothesis)
            _check_likelihood(like)
            weights[hypothesis] = like * p
        evidence = sum(weights.values())
        if evidence <= 0.0:
            raise InformationGainError(
                "observation has zero probability under every hypothesis"
            )
        posterior = {h: w / evidence for h, w in weights.items()}
        before = entropy(prior.values())
        after = entropy(posterior.values())
        gain = before - after
        max_h = self.max_entropy
        normalized = gain / max_h if max_h > 0.0 else 0.0
        self._beliefs = posterior
        return BeliefUpdate(
            observation=observation,
            prior=prior,
            posterior=dict(posterior),
            entropy_before=before,
            entropy_after=after,
            gain_bits=gain,
            normalized_gain=normalized,
        )


@dataclass(frozen=True)
class ProgressSnapshot:
    """Counts used by the proxy estimator.

    Attributes:
        open_failures: number of currently open failures (for example failing tests).
        passed_checks: number of passed verification checks.
        completed_milestones: number of completed milestones.
    """

    open_failures: int = 0
    passed_checks: int = 0
    completed_milestones: int = 0


class ProxyInformationGain:
    """PROXY information gain from progress counters. Not mutual information.

    See the module docstring for the exact formula. ``label`` always states that
    this is a proxy so downstream reports cannot mistake it for the real thing.
    """

    label: str = PROXY_LABEL

    def __init__(self, initial: ProgressSnapshot) -> None:
        self._initial = initial

    @property
    def initial(self) -> ProgressSnapshot:
        """The snapshot all normalizations are relative to."""
        return self._initial

    def components(self, snapshot: ProgressSnapshot) -> tuple[float, float, float]:
        """Return the three normalized terms for ``snapshot``.

        Order: (reduction in open failures, increase in passed checks,
        increase in completed milestones).
        """
        init = self._initial
        failures = max(0, init.open_failures - snapshot.open_failures) / max(
            init.open_failures, 1
        )
        checks = max(0, snapshot.passed_checks - init.passed_checks) / max(
            init.passed_checks, 1
        )
        milestones = max(0, snapshot.completed_milestones - init.completed_milestones) / max(
            init.completed_milestones, 1
        )
        return failures, checks, milestones

    def cumulative(self, snapshot: ProgressSnapshot) -> float:
        """Return the cumulative proxy score of ``snapshot`` relative to the initial one."""
        return sum(self.components(snapshot))

    def step_gain(self, previous: ProgressSnapshot, current: ProgressSnapshot) -> float:
        """Return ``cumulative(current) - cumulative(previous)`` (may be negative on regress)."""
        return self.cumulative(current) - self.cumulative(previous)


@dataclass(frozen=True)
class InformationGainEstimate:
    """An information-gain value together with its provenance.

    Attributes:
        value: the estimated gain.
        source: ``"belief"`` (Bayesian), ``"proxy"`` (heuristic), or ``"none"``.
        is_proxy: true when the value comes from the proxy estimator.
    """

    value: float
    source: Literal["belief", "proxy", "none"]
    is_proxy: bool


class InformationGainEstimator:
    """Chooses the real estimator when hypotheses exist, otherwise the proxy.

    Args:
        tracker: optional belief tracker; used whenever an observation is given.
        proxy: optional proxy estimator; used as the fallback.
        normalize: if true the belief gain is divided by ``log2(k)`` so it lies
            in ``[-1, 1]``; by default the raw gain in bits is returned.
    """

    def __init__(
        self,
        tracker: HypothesisBeliefTracker | None = None,
        proxy: ProxyInformationGain | None = None,
        *,
        normalize: bool = False,
    ) -> None:
        self._tracker = tracker
        self._proxy = proxy
        self._normalize = normalize

    def estimate(
        self,
        *,
        observation: str | None = None,
        previous: ProgressSnapshot | None = None,
        current: ProgressSnapshot | None = None,
    ) -> InformationGainEstimate:
        """Return the estimated information gain for one step."""
        if self._tracker is not None and observation is not None:
            update = self._tracker.update(observation)
            value = update.normalized_gain if self._normalize else update.gain_bits
            return InformationGainEstimate(value=value, source="belief", is_proxy=False)
        if self._proxy is not None and previous is not None and current is not None:
            return InformationGainEstimate(
                value=self._proxy.step_gain(previous, current),
                source="proxy",
                is_proxy=True,
            )
        return InformationGainEstimate(value=0.0, source="none", is_proxy=False)
