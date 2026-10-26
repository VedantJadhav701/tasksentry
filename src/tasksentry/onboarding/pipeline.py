"""One-call pipeline: sample record -> recognized format -> synthesized harness -> governed run.

analyze(): recognition + spec + static SOP graph (no execution).
run():     the above plus an engine dry-run on a simulated backend and a replayable event trace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from tasksentry.harness.engine import UniversalEngine
from tasksentry.onboarding.infer import RecordProfile, profile_record
from tasksentry.onboarding.synth import (
    HarnessSpec,
    SimulatedBackend,
    build_pack,
    refine_with_llm,
    synthesize,
)

LLM = Callable[[str], str]


def build_graph(spec: HarnessSpec) -> dict[str, Any]:
    nodes = [
        {
            "id": p.name,
            "kind": "probe",
            "label": p.title[:44],
            "step": p.step,
            "command": p.commands[0] if p.commands else "",
        }
        for p in spec.probes
    ]
    nodes += [
        {"id": "diagnosis", "kind": "diagnosis", "label": "Bayesian diagnosis"},
        {"id": "remediation", "kind": "remediation", "label": "Gated remediation"},
        {"id": "verification", "kind": "verification", "label": "SPRT verification"},
        {"id": "resolved", "kind": "terminal", "label": "Resolved"},
        {"id": "escalated", "kind": "terminal", "label": "Escalated"},
    ]
    edges = [{"from": p.name, "to": "diagnosis"} for p in spec.probes]
    edges += [
        {"from": "diagnosis", "to": "remediation"},
        {"from": "remediation", "to": "verification"},
        {"from": "verification", "to": "resolved"},
        {"from": "diagnosis", "to": "escalated"},
        {"from": "remediation", "to": "escalated"},
        {"from": "verification", "to": "escalated"},
    ]
    return {"nodes": nodes, "edges": edges}


def _profile_and_spec(raw: Any, llm: LLM | None) -> tuple[RecordProfile, HarnessSpec]:
    profile = profile_record(raw, llm)
    spec = synthesize(profile)
    if llm is not None:
        spec = refine_with_llm(spec, profile, llm)
    return profile, spec


def analyze(raw: Any, llm: LLM | None = None) -> dict[str, Any]:
    profile, spec = _profile_and_spec(raw, llm)
    return {"profile": asdict(profile), "spec": spec.to_dict(), "graph": build_graph(spec)}


def run(
    raw: Any,
    llm: LLM | None = None,
    truth: str | None = None,
    flip_prob: float = 0.0,
    approve_high_risk: bool = False,
    signing_key: bytes | None = b"change-me",
) -> dict[str, Any]:
    profile, spec = _profile_and_spec(raw, llm)
    true_h = truth if truth in spec.hypotheses else max(spec.priors, key=lambda k: spec.priors[k])
    backend = SimulatedBackend(spec, true_h, flip_prob=flip_prob)
    pack = build_pack(spec, backend)
    engine = UniversalEngine(
        pack, signing_key=signing_key, approver=(lambda *_: True) if approve_high_risk else None
    )
    res = engine.solve()
    return {
        "profile": asdict(profile),
        "spec": spec.to_dict(),
        "graph": build_graph(spec),
        "truth_simulated": true_h,
        "simulated": True,
        "result": res.to_dict(),
        "events": res.events,
    }
