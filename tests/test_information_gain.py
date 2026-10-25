"""Tests for entropy, Bayesian belief updates, and the proxy fallback."""

import math

import pytest

from tasksentry.exceptions import InformationGainError
from tasksentry.math.information_gain import (
    PROXY_LABEL,
    HypothesisBeliefTracker,
    InformationGainEstimator,
    LikelihoodModel,
    ProgressSnapshot,
    ProxyInformationGain,
    TableLikelihoodModel,
    entropy,
)


def _tracker() -> HypothesisBeliefTracker:
    table = {
        "failure in pricing.py": {"pricing": 0.9, "billing": 0.1},
        "failure in billing.py": {"pricing": 0.1, "billing": 0.9},
    }
    return HypothesisBeliefTracker(
        {"pricing": 0.5, "billing": 0.5}, TableLikelihoodModel(table)
    )


def test_entropy_known_values() -> None:
    assert entropy([0.5, 0.5]) == pytest.approx(1.0)
    assert entropy([1.0, 0.0]) == 0.0
    assert entropy([0.25] * 4) == pytest.approx(2.0)
    assert entropy([0.9, 0.1]) == pytest.approx(0.468996, abs=1e-6)


def test_entropy_rejects_invalid_probabilities() -> None:
    with pytest.raises(InformationGainError):
        entropy([0.5, -0.1])
    with pytest.raises(InformationGainError):
        entropy([float("nan")])


def test_bayes_update_matches_hand_calculation() -> None:
    update = _tracker().update("failure in pricing.py")
    assert update.posterior["pricing"] == pytest.approx(0.9)
    assert update.posterior["billing"] == pytest.approx(0.1)
    assert update.entropy_before == pytest.approx(1.0)
    assert update.entropy_after == pytest.approx(0.468996, abs=1e-6)
    assert update.gain_bits == pytest.approx(1.0 - 0.468996, abs=1e-6)
    assert update.normalized_gain == pytest.approx(update.gain_bits)  # log2(2) == 1


def test_uninformative_observation_has_zero_gain() -> None:
    update = _tracker().update("something unrelated")
    assert update.gain_bits == pytest.approx(0.0, abs=1e-12)
    assert update.posterior == pytest.approx({"pricing": 0.5, "billing": 0.5})


def test_contradicting_evidence_can_have_negative_realized_gain() -> None:
    tracker = _tracker()
    tracker.update("failure in pricing.py")
    tracker.update("failure in pricing.py")
    contradiction = tracker.update("failure in billing.py")
    assert contradiction.gain_bits < 0.0


def test_repeated_evidence_converges_and_tracks_most_likely() -> None:
    tracker = _tracker()
    gains = [tracker.update("failure in pricing.py").gain_bits for _ in range(4)]
    assert gains[0] > gains[-1] > 0.0  # diminishing returns
    name, probability = tracker.most_likely()
    assert name == "pricing"
    assert probability > 0.99
    assert tracker.entropy < 0.1
    tracker.reset()
    assert tracker.beliefs == {"pricing": 0.5, "billing": 0.5}


def test_zero_probability_observation_raises() -> None:
    table = {"impossible": {"a": 0.0, "b": 0.0}}
    tracker = HypothesisBeliefTracker({"a": 0.5, "b": 0.5}, TableLikelihoodModel(table))
    with pytest.raises(InformationGainError, match="zero probability"):
        tracker.update("impossible")


def test_prior_validation() -> None:
    model = TableLikelihoodModel({})
    with pytest.raises(InformationGainError):
        HypothesisBeliefTracker({}, model)
    with pytest.raises(InformationGainError):
        HypothesisBeliefTracker({"a": 0.7, "b": 0.7}, model)
    with pytest.raises(InformationGainError):
        HypothesisBeliefTracker({"a": -0.2, "b": 1.2}, model)
    normalized = HypothesisBeliefTracker({"a": 2.0, "b": 2.0}, model, normalize_priors=True)
    assert normalized.beliefs == {"a": 0.5, "b": 0.5}
    assert math.isclose(normalized.max_entropy, 1.0)
    with pytest.raises(InformationGainError):
        TableLikelihoodModel({"x": {"a": -1.0}})


def test_table_likelihood_matches_after_normalization_and_is_a_protocol() -> None:
    model = TableLikelihoodModel({"Failure at 2026-10-25T10:00:00Z": {"a": 0.7}}, default=0.2)
    assert isinstance(model, LikelihoodModel)
    assert model.likelihood("failure at 2027-01-01T00:00:00Z", "a") == 0.7
    assert model.likelihood("failure at 2027-01-01T00:00:00Z", "other") == 0.2
    assert model.likelihood("unknown", "a") == 0.2


def test_proxy_formula_and_denominators() -> None:
    initial = ProgressSnapshot(open_failures=4, passed_checks=0, completed_milestones=0)
    proxy = ProxyInformationGain(initial)
    assert proxy.label == PROXY_LABEL
    assert "PROXY" in proxy.label
    # 2 of 4 failures closed -> 0.5; passed_checks denominator max(0,1)=1; 1 milestone / 1.
    snapshot = ProgressSnapshot(open_failures=2, passed_checks=1, completed_milestones=1)
    assert proxy.components(snapshot) == pytest.approx((0.5, 1.0, 1.0))
    assert proxy.cumulative(snapshot) == pytest.approx(2.5)


def test_proxy_never_rewards_regression_in_cumulative_terms() -> None:
    initial = ProgressSnapshot(open_failures=2, passed_checks=2, completed_milestones=1)
    proxy = ProxyInformationGain(initial)
    worse = ProgressSnapshot(open_failures=5, passed_checks=0, completed_milestones=0)
    assert proxy.components(worse) == (0.0, 0.0, 0.0)


def test_proxy_step_gains_telescope_to_cumulative() -> None:
    initial = ProgressSnapshot(open_failures=3, passed_checks=1, completed_milestones=0)
    proxy = ProxyInformationGain(initial)
    s0 = proxy.initial
    s1 = ProgressSnapshot(open_failures=2, passed_checks=1, completed_milestones=0)
    s2 = ProgressSnapshot(open_failures=0, passed_checks=3, completed_milestones=1)
    total = proxy.step_gain(s0, s1) + proxy.step_gain(s1, s2)
    assert total == pytest.approx(proxy.cumulative(s2))
    assert proxy.step_gain(s2, s1) < 0.0  # regression is reflected per step


def test_estimator_prefers_belief_then_proxy_then_none() -> None:
    snap0 = ProgressSnapshot(open_failures=2)
    snap1 = ProgressSnapshot(open_failures=1)
    both = InformationGainEstimator(_tracker(), ProxyInformationGain(snap0))
    belief = both.estimate(observation="failure in pricing.py", previous=snap0, current=snap1)
    assert (belief.source, belief.is_proxy) == ("belief", False)
    assert belief.value > 0.0

    proxy_only = InformationGainEstimator(proxy=ProxyInformationGain(snap0))
    proxy = proxy_only.estimate(previous=snap0, current=snap1)
    assert (proxy.source, proxy.is_proxy) == ("proxy", True)
    assert proxy.value == pytest.approx(0.5)

    nothing = InformationGainEstimator().estimate(observation="x")
    assert (nothing.source, nothing.value) == ("none", 0.0)


def test_estimator_normalize_option_scales_by_max_entropy() -> None:
    table = {"clue": {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0}}
    priors = dict.fromkeys("abcd", 0.25)
    raw = InformationGainEstimator(HypothesisBeliefTracker(priors, TableLikelihoodModel(table)))
    scaled = InformationGainEstimator(
        HypothesisBeliefTracker(priors, TableLikelihoodModel(table)), normalize=True
    )
    assert raw.estimate(observation="clue").value == pytest.approx(2.0)
    assert scaled.estimate(observation="clue").value == pytest.approx(1.0)
