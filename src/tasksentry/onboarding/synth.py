"""Synthesize a HarnessSpec (hypotheses, probes, remediations, escalations) from a RecordProfile.

Deterministic rules build a working spec; an optional LLM (e.g. Ollama beam:cloud) may refine
probe sensitivities. Safety guard: the LLM can only RAISE a remediation's risk tier, never lower it.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from tasksentry.harness.domain import DomainPack, Remediation
from tasksentry.math.bayes_rca import Probe
from tasksentry.onboarding.infer import RecordProfile, extract_json

OWNED, BASE = 0.92, 0.04
_SYSTEM = re.compile(r"power.?cycle|hard reset|reboot (the )?host", re.I)
_REVERSIBLE = re.compile(r"redeploy|restart|unlock|resync|reload|re-?run|reset", re.I)
_RANK = {"reversible_write": 0, "system_write": 1, "irreversible_write": 2}


def slug(s: str, n: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:n] or "unknown"


@dataclass
class ProbeSpec:
    name: str
    step: int
    title: str
    commands: list[str]
    owns: list[str]
    cost: float = 1.0


@dataclass
class RemediationSpec:
    hypothesis: str
    name: str
    risk: str
    source_step: int


@dataclass
class HarnessSpec:
    domain: str
    hypotheses: list[str]
    priors: dict[str, float]
    probes: list[ProbeSpec]
    remediations: list[RemediationSpec]
    escalation: dict[str, str]
    label_hint: str = ""
    notes: list[str] = field(default_factory=list)
    source: str = "deterministic"
    sensitivity: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def synthesize(profile: RecordProfile) -> HarnessSpec:
    hyps: list[str] = []
    probes: list[ProbeSpec] = []
    rems: list[RemediationSpec] = []
    esc: dict[str, str] = {}
    notes: list[str] = []
    owner_step: dict[str, Any] = {}

    def add_hyp(h: str, step: Any) -> str:
        if h not in hyps:
            hyps.append(h)
            owner_step[h] = step
        return h

    for st in profile.steps:
        if st.mappings:
            for left, right in st.mappings:
                h = add_hyp(slug(right), st)
                probes.append(
                    ProbeSpec(
                        f"s{st.number}_{slug(left, 24)}",
                        st.number,
                        f"{st.title}: {left}",
                        st.commands[:3],
                        [h],
                        1.0,
                    )
                )
                if st.escalate_documented and st.escalate:
                    esc.setdefault(h, st.escalate)
            continue
        if not st.subissue:
            notes.append(f"step {st.number} has no failure subissue; skipped as a probe")
            continue
        h = add_hyp(slug(st.subissue), st)
        probes.append(
            ProbeSpec(
                f"s{st.number}_{slug(st.title, 24)}",
                st.number,
                st.title,
                st.commands[:3],
                [h],
                1.0 + 0.5 * (st.number > 3),
            )
        )
        if st.escalate_documented and st.escalate:
            esc.setdefault(h, st.escalate)
        text = " ".join(st.actions)
        if not st.stop:
            if _SYSTEM.search(text):
                rems.append(RemediationSpec(h, "power_cycle", "system_write", st.number))
            elif _REVERSIBLE.search(text):
                kw = _REVERSIBLE.search(text)
                rems.append(
                    RemediationSpec(
                        h,
                        slug(kw.group(0)) + "_action" if kw else "fix",
                        "reversible_write",
                        st.number,
                    )
                )
    if len(hyps) < 2:
        raise ValueError("Could not derive >= 2 root-cause hypotheses from this record.")
    priors = dict.fromkeys(hyps, 1.0)
    stem = re.sub(r"(failure|fail|alarm|notif|ani)", "", profile.label_hint.lower())
    boosted = [h for h in hyps if len(stem) >= 4 and stem in h]
    for h in boosted:
        priors[h] = 3.0
    if boosted:
        notes.append(f"prior boosted x3 for {boosted} from label hint '{profile.label_hint}'")
    tot = sum(priors.values())
    priors = {h: v / tot for h, v in priors.items()}
    sens = {p.name: {h: (OWNED if h in p.owns else BASE) for h in hyps} for p in probes}
    notes.append(
        "sensitivities are heuristic (owned=0.92, other=0.04); refine with labelled data or LLM"
    )
    return HarnessSpec(
        domain=slug(profile.category or "uploaded-domain", 40),
        hypotheses=hyps,
        priors=priors,
        probes=probes,
        remediations=rems,
        escalation=esc,
        label_hint=profile.label_hint,
        notes=notes,
        sensitivity=sens,
    )


def refine_with_llm(
    spec: HarnessSpec, profile: RecordProfile, llm: Callable[[str], str]
) -> HarnessSpec:
    prompt = (
        "You are a domain expert tuning a Bayesian troubleshooting harness. Reply ONLY with JSON: "
        '{"sensitivity_overrides": {"<probe>": '
        '{"<hypothesis>": <0..1 P(probe abnormal | hypothesis)>}}, '
        '"risk_overrides": {"<hypothesis>": "system_write"}, "notes": "<one line>"}.\n'
        f"Hypotheses: {spec.hypotheses}\nProbes: {[(p.name, p.title) for p in spec.probes]}\n"
        f"Ticket: {profile.instruction[:600]}"
    )
    try:
        hint = extract_json(llm(prompt)) or {}
    except Exception as exc:
        spec.notes.append(f"LLM unavailable ({exc}); kept deterministic spec")
        return spec
    changed = 0
    for pname, row in (hint.get("sensitivity_overrides") or {}).items():
        if pname in spec.sensitivity and isinstance(row, dict):
            for h, v in row.items():
                if h in spec.hypotheses and isinstance(v, int | float):
                    spec.sensitivity[pname][h] = min(max(float(v), 0.01), 0.99)
                    changed += 1
    for h, risk in (hint.get("risk_overrides") or {}).items():
        for r in spec.remediations:
            if r.hypothesis == h and _RANK.get(str(risk), -1) > _RANK[r.risk]:
                r.risk = str(risk)  # raise only
                changed += 1
    spec.source = "deterministic+llm"
    spec.notes.append(
        f"LLM refinement applied ({changed} adjustments): {str(hint.get('notes', ''))[:160]}"
    )
    return spec


class SimulatedBackend:
    """Dry-run backend: probes report the signature of a chosen true root cause.

    Replace with real callables (SSH, kubectl, REST...) to run against live systems.
    """

    def __init__(
        self,
        spec: HarnessSpec,
        truth: str,
        flip_prob: float = 0.0,
        rng: random.Random | None = None,
    ) -> None:
        self.spec, self.truth, self.flip_prob = spec, truth, flip_prob
        self.rng = rng or random.Random(0)
        self.healed = False
        self.log: list[str] = []

    def run_probe(self, name: str) -> bool:
        out = self.spec.sensitivity[name][self.truth] >= 0.5
        if self.flip_prob > 0 and self.rng.random() < self.flip_prob:
            out = not out
        return out

    def fix(self, hypothesis: str) -> Callable[[], dict[str, Any]]:
        def run() -> dict[str, Any]:
            if hypothesis == self.truth:
                self.healed = True
            return {"status": "SUCCESS" if self.healed else "NO_EFFECT"}

        return run

    def verify(self) -> bool:
        return self.healed


def build_pack(spec: HarnessSpec, backend: SimulatedBackend) -> DomainPack:
    rems = {
        r.hypothesis: Remediation(
            r.name,
            r.risk,
            backend.fix(r.hypothesis),
            success_prob=0.85 if r.risk == "reversible_write" else 0.8,
            benefit=100.0,
            harm=15.0 if r.risk == "reversible_write" else 80.0,
            cost=1.0 if r.risk == "reversible_write" else 5.0,
        )
        for r in spec.remediations
    }
    return DomainPack(
        name=spec.domain,
        priors=spec.priors,
        probes=[Probe(p.name, spec.sensitivity[p.name], p.cost) for p in spec.probes],
        run_probe=backend.run_probe,
        verify=backend.verify,
        remediations=rems,
        escalation=spec.escalation,
        default_escalation="Specialist team (not documented in record)",
    )
