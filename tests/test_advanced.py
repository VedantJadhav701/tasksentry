import random

import pytest

from tasksentry.harness.engine import UniversalEngine
from tasksentry.math.bandit import ThompsonSelector
from tasksentry.math.bayes_rca import BayesRCA, Probe, entropy, pool_with_model
from tasksentry.math.conformal import SplitConformal
from tasksentry.math.hashchain import HashChain
from tasksentry.math.risk import gate_remediation, wilson_interval
from tasksentry.math.sequential import CUSUM, SPRT
from tasksentry.telecom.analytics import run_benchmark
from tasksentry.telecom.analytics import state_for_label as state_for
from tasksentry.telecom.pack import build_from_state


def test_bayes_converges_and_reduces_entropy():
    probes = [Probe("a", {"x": 0.95, "y": 0.05}), Probe("b", {"x": 0.5, "y": 0.5})]
    b = BayesRCA({"x": 0.5, "y": 0.5}, probes)
    assert b.expected_information_gain("a") > b.expected_information_gain("b")
    assert b.next_probe() == "a"
    h0 = entropy(b.posterior)
    b.update("a", True)
    assert entropy(b.posterior) < h0
    assert b.map_hypothesis()[0] == "x"


def test_pooling_moves_toward_model():
    post = {"x": 0.5, "y": 0.5}
    pooled = pool_with_model(post, {"x": 0.9, "y": 0.1}, 0.5)
    assert pooled["x"] > 0.5 and abs(sum(pooled.values()) - 1) < 1e-9


def test_conformal_coverage_on_synthetic():
    rng = random.Random(1)
    data = []
    for _ in range(2000):
        truth = rng.choice("abc")
        probs = {h: rng.random() for h in "abc"}
        probs[truth] += 0.8
        s = sum(probs.values())
        data.append(({k: v / s for k, v in probs.items()}, truth))
    cp = SplitConformal(0.1).fit(data[:1000])
    assert cp.coverage(data[1000:]) >= 0.87


def test_sprt_and_cusum():
    s = SPRT()
    d = "continue"
    while d == "continue":
        d = s.update(True)
    assert d == "accept_h1" and s.n == 5
    s2 = SPRT()
    assert [s2.update(False), s2.update(False)][-1] == "accept_h0"
    c = CUSUM(k=0.5, h=2.0)
    assert not c.update(0.0) and any(c.update(2.0) for _ in range(3))


def test_bandit_learns():
    t = ThompsonSelector(["good", "bad"], seed=3)
    for _ in range(300):
        arm = t.select()
        t.update(arm, 0.9 if arm == "good" else 0.1)
    assert t.mean("good") > t.mean("bad")


def test_risk_gate_and_wilson():
    assert gate_remediation("system_write", 0.99, 0.99, 100, 80, 5).requires_approval
    assert gate_remediation("reversible_write", 0.97, 0.95, 100, 10, 1).auto_execute
    assert gate_remediation(
        "reversible_write", 0.97, 0.95, 100, 10, 1, ambiguous=True
    ).requires_approval
    lo, hi = wilson_interval(90, 100)
    assert 0.8 < lo < 0.9 < hi < 0.96


def test_hashchain_tamper_detection():
    c = HashChain(b"k")
    for i in range(5):
        c.append({"i": i})
    assert c.verify()
    root = c.root()
    c.entries[2].payload["i"] = 99
    assert not c.verify() and c.root() == root  # hashes unchanged, verify catches payload edit


@pytest.mark.parametrize(
    "label,expected",
    [
        ("software", "software"),
        ("timing", "timing"),
        ("admin_lock", "admin_lock"),
    ],
)
def test_engine_self_heals(label, expected):
    res = UniversalEngine(build_from_state(state_for(label))).solve()
    assert res.diagnosis.hypothesis == expected
    assert res.status == "resolved" and res.approval == "auto"
    assert res.chain_valid and res.verification["healthy"]


@pytest.mark.parametrize("label", ["midhaul", "fronthaul"])
def test_engine_escalates_unfixable(label):
    res = UniversalEngine(build_from_state(state_for(label))).solve()
    assert res.diagnosis.hypothesis == label
    assert res.status == "escalated" and res.escalation_team


def test_hardware_needs_approval():
    denied = UniversalEngine(build_from_state(state_for("hardware"))).solve()
    assert denied.diagnosis.hypothesis == "hardware"
    assert denied.status == "escalated" and denied.approval == "denied_or_pending"
    ok = UniversalEngine(build_from_state(state_for("hardware")), approver=lambda *_: True).solve()
    assert ok.status == "resolved" and ok.approval == "approved"


def test_brain_failure_is_non_fatal():
    def bad(_):
        raise RuntimeError("ollama down")

    res = UniversalEngine(build_from_state(state_for("software")), brain=bad).solve()
    assert res.status == "resolved" and "unavailable" in res.diagnosis.brain_analysis


def test_benchmark_noisy_sensors():
    out = run_benchmark(state_for, flip_prob=0.05, episodes_per_class=30, seed=7)
    print(out)
    assert out["top1_accuracy"] >= 0.85
    assert out["conformal_coverage"] >= 0.85
