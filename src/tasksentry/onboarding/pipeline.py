"""One-call pipeline: sample record -> recognized format -> synthesized harness -> governed run.

analyze(): recognition + spec + static SOP graph (no execution).
run():     the above plus a governed simulation preview or an explicitly registered live backend.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from tasksentry.harness.backend import DomainBackend, default_backend_registry
from tasksentry.harness.engine import UniversalEngine
from tasksentry.onboarding.infer import RecordProfile, extract_json, profile_record
from tasksentry.onboarding.synth import (
    HarnessSpec,
    SimulatedBackend,
    build_pack,
    refine_with_llm,
    synthesize,
)

LLM = Callable[[str], str]


def _brain_from_llm(llm: LLM, spec: HarnessSpec) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Turn the optional cloud model into an advisory, schema-checked RCA expert."""

    def brain(context: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "You are a domain RCA advisor. Reply only with JSON containing "
            '{"probs": {"hypothesis": 0..1}, "analysis": "brief evidence summary"}. '
            "Use only the supplied hypotheses and observations; do not invent telemetry.\n"
            f"Hypotheses: {spec.hypotheses}\nContext: {json.dumps(context, default=str)}"
        )
        parsed = extract_json(llm(prompt)) or {}
        probs = parsed.get("probs")
        valid = (
            {str(k): float(v) for k, v in probs.items() if k in spec.hypotheses}
            if isinstance(probs, dict)
            else {}
        )
        return {"probs": valid, "analysis": str(parsed.get("analysis", ""))[:1000]}

    return brain


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
    signing_key: bytes | None = None,
    execution_mode: str = "simulation",
    backend_id: str | None = None,
    backend: DomainBackend | None = None,
) -> dict[str, Any]:
    profile, spec = _profile_and_spec(raw, llm)
    if execution_mode not in {"simulation", "live"}:
        raise ValueError("execution_mode must be 'simulation' or 'live'")
    if execution_mode == "live" and signing_key is None:
        configured_key = os.environ.get("TASKSENTRY_AUDIT_KEY")
        if not configured_key:
            raise ValueError("Live execution requires TASKSENTRY_AUDIT_KEY for signed receipts")
        signing_key = configured_key.encode("utf-8")
    true_h = truth if truth in spec.hypotheses else max(spec.priors, key=lambda k: spec.priors[k])
    simulated_backend: SimulatedBackend | None = None
    if execution_mode == "simulation":
        simulated_backend = SimulatedBackend(spec, true_h, flip_prob=flip_prob)
        selected_backend: DomainBackend = simulated_backend
    else:
        candidate = backend or (default_backend_registry.get(backend_id) if backend_id else None)
        if candidate is None:
            raise ValueError(
                "Live execution requires a registered backend_id or an injected backend"
            )
        selected_backend = candidate
    pack = build_pack(spec, selected_backend)
    engine = UniversalEngine(
        pack,
        signing_key=signing_key,
        approver=(lambda *_: True) if approve_high_risk else None,
        brain=_brain_from_llm(llm, spec) if llm is not None else None,
    )
    res = engine.solve()
    return {
        "profile": asdict(profile),
        "spec": spec.to_dict(),
        "graph": build_graph(spec),
        "truth_simulated": true_h if execution_mode == "simulation" else None,
        "simulated": execution_mode == "simulation",
        "execution_mode": execution_mode,
        "backend_id": selected_backend.name,
        "result": res.to_dict(),
        "events": res.events,
    }
