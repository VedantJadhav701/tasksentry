"""Dataset analytics, prior estimation, and noisy-sensor benchmark with conformal calibration."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from tasksentry.harness.engine import UniversalEngine
from tasksentry.math.conformal import SplitConformal
from tasksentry.math.risk import wilson_interval
from tasksentry.telecom.pack import (
    HYPOTHESES,
    build_from_state,
    default_priors,
    hypothesis_of_failure,
)


def estimate_priors(tickets: Iterable[Any]) -> dict[str, float]:
    """Dirichlet-smoothed class priors from ticket failure types (use the 3,813 dataset)."""
    counts: Counter[str] = Counter()
    for t in tickets:
        h = hypothesis_of_failure(t.metadata.failure_type)
        if h:
            counts[h] += 1
    return default_priors(dict(counts))


def summarize(results: list[Any], manual_mttr_seconds: float | None = None) -> dict[str, Any]:
    """Aggregate TelecomResolutionResult objects into the Analytics-tab payload."""
    n = len(results)
    resolved = sum(1 for r in results if r.status == "resolved")
    healed = sum(1 for r in results if getattr(r, "self_healing_applied", False))
    lo, hi = wilson_interval(healed, n)
    teams = Counter(
        r.escalation_team for r in results if r.status == "escalated" and r.escalation_team
    )
    causes = Counter(r.rca_driver for r in results)
    mttr = sum(r.wall_time_seconds for r in results) / max(n, 1)
    out: dict[str, Any] = {
        "tickets": n,
        "resolved_rate": round(resolved / max(n, 1), 4),
        "autonomous_resolution_rate": round(healed / max(n, 1), 4),
        "autonomous_resolution_ci95": [round(lo, 4), round(hi, 4)],
        "mttr_seconds_agent": round(mttr, 4),
        "failure_distribution": dict(causes),
        "escalations_by_team": dict(teams),
    }
    if manual_mttr_seconds:
        out["mttr_speedup_x"] = round(manual_mttr_seconds / max(mttr, 1e-9), 1)
    return out


def state_for_label(label: str) -> Any:
    """Simulation state for a true root cause, with physically consistent F1-C.

    NOTE: TelecomSimulationState.from_ticket_failure_type leaves f1c_connected=False
    for timing / fronthaul / admin cases, which makes them look like midhaul to any
    probe-based diagnosis. Here F1-C is only down for midhaul (and hardware-host-down).
    """
    from tasksentry.telecom.tools import TelecomSimulationState as S

    if label == "software":
        return S.from_ticket_failure_type("softwarefailure")
    if label == "midhaul":
        return S.from_ticket_failure_type("midhaulfailure")
    if label == "timing":
        return S(oru_timing_locked=False, f1c_connected=True, first_alarm="notifAniTimingUnlocked")
    if label == "fronthaul":
        return S(f1c_connected=True, first_alarm="notifAniRuConnectivityFailure")
    if label == "admin_lock":
        return S(admin_state="LOCKED", f1c_connected=True, first_alarm="mgmtoperation")
    if label == "hardware":
        return S(
            host_reachable=False,
            has_sysmon_reboot=True,
            f1c_connected=True,
            first_alarm="aniCellDown",
        )
    raise KeyError(label)


def run_benchmark(
    state_factory: Callable[[str], Any] = state_for_label,
    flip_prob: float = 0.05,
    episodes_per_class: int = 40,
    alpha: float = 0.1,
    seed: int = 0,
) -> dict[str, Any]:
    """Simulate noisy probes, calibrate conformal on half, evaluate on the other half.

    state_factory(label) -> fresh simulation state for that true root cause. Results
    describe the *simulator*; treat them as a regression test, not field accuracy.
    """
    rng = random.Random(seed)
    records: list[tuple[dict[str, float], str]] = []
    top1 = 0
    probes_used = 0
    for label in HYPOTHESES:
        for _ in range(episodes_per_class):
            pack = build_from_state(state_factory(label), flip_prob=flip_prob, rng=rng)
            res = UniversalEngine(pack, signing_key=None, approver=lambda *_: True).solve()
            records.append((res.diagnosis.posterior, label))
            top1 += res.diagnosis.hypothesis == label
            probes_used += len(res.diagnosis.probes_run)
    rng.shuffle(records)
    half = len(records) // 2
    cal, test = records[:half], records[half:]
    cp = SplitConformal(alpha).fit(cal)
    sizes = [len(cp.predict_set(p)) for p, _ in test]
    return {
        "episodes": len(records),
        "flip_prob": flip_prob,
        "top1_accuracy": round(top1 / len(records), 4),
        "mean_probes": round(probes_used / len(records), 2),
        "conformal_alpha": alpha,
        "conformal_coverage": round(cp.coverage(test), 4),
        "mean_set_size": round(sum(sizes) / max(len(sizes), 1), 3),
    }
