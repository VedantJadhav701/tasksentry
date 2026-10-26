"""Universal 3-agent engine: Diagnostic -> Remediation -> Verification Auditor.

Diagnostic agent : Bayesian RCA, probes chosen by information gain per cost,
                   optional pooling with a domain-trained model, conformal set.
Remediation agent: expected-utility + risk-tier gate; human approval callback.
Verification     : Wald SPRT over repeated health reads; signs the hash-chained
                   audit log (HMAC) and reports the Merkle root.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from tasksentry.harness.domain import DomainPack, Remediation
from tasksentry.math.bayes_rca import BayesRCA, entropy, pool_with_model
from tasksentry.math.conformal import SplitConformal
from tasksentry.math.hashchain import HashChain
from tasksentry.math.risk import gate_remediation
from tasksentry.math.sequential import SPRT

Brain = Callable[[dict[str, Any]], dict[str, Any]]
Approver = Callable[[Remediation, "Diagnosis"], bool]


@dataclass
class Diagnosis:
    hypothesis: str
    confidence: float
    posterior: dict[str, float]
    prediction_set: list[str]
    probes_run: list[tuple[str, bool]]
    entropy_start_bits: float
    entropy_end_bits: float
    brain_analysis: str = ""


@dataclass
class EngineResult:
    status: str  # resolved | escalated
    domain: str
    diagnosis: Diagnosis
    remediation: dict[str, Any] | None = None
    approval: str = "not_needed"
    verification: dict[str, Any] | None = None
    escalation_team: str | None = None
    escalation_reason: str | None = None
    chain_root: str = ""
    chain_valid: bool = False
    chain_signed: bool = False
    chain_length: int = 0
    wall_time_seconds: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DiagnosticAgent:
    def __init__(
        self,
        pack: DomainPack,
        chain: HashChain,
        tau: float,
        max_probes: int,
        conformal: SplitConformal | None,
        brain: Brain | None,
        brain_weight: float,
    ):
        self.pack, self.chain, self.tau, self.max_probes = pack, chain, tau, max_probes
        self.conformal, self.brain, self.brain_weight = conformal, brain, brain_weight

    def run(self) -> Diagnosis:
        bayes = BayesRCA(self.pack.priors, self.pack.probes)
        h_start = entropy(bayes.posterior)
        ran: list[tuple[str, bool]] = []
        for _ in range(self.max_probes):
            if bayes.map_hypothesis()[1] >= self.tau:
                break
            name = bayes.next_probe()
            if name is None:
                break
            abnormal = bool(self.pack.run_probe(name))
            bayes.update(name, abnormal)
            ran.append((name, abnormal))
            top, conf = bayes.map_hypothesis()
            self.chain.append(
                {
                    "event": "probe",
                    "probe": name,
                    "abnormal": abnormal,
                    "top": top,
                    "confidence": round(conf, 6),
                    "entropy_bits": round(entropy(bayes.posterior), 6),
                    "posterior": {h: round(p, 4) for h, p in bayes.posterior.items()},
                }
            )
        post = dict(bayes.posterior)
        analysis = ""
        if self.brain is not None:
            try:
                out = self.brain(
                    {"domain": self.pack.name, "observations": dict(ran), "posterior": post}
                )
                analysis = str(out.get("analysis", ""))
                probs = out.get("probs")
                if isinstance(probs, dict) and probs:
                    post = pool_with_model(
                        post, {k: float(v) for k, v in probs.items()}, self.brain_weight
                    )
            except Exception as exc:  # brain is advisory; never block diagnosis
                analysis = f"brain unavailable: {exc}"
        top = max(post, key=lambda k: post[k])
        pset = self.conformal.predict_set(post) if self.conformal else [top]
        self.chain.append(
            {
                "event": "diagnosis",
                "hypothesis": top,
                "confidence": round(post[top], 6),
                "set": pset,
            }
        )
        return Diagnosis(top, post[top], post, pset, ran, h_start, entropy(post), analysis)


class RemediationAgent:
    def __init__(self, pack: DomainPack, chain: HashChain, approver: Approver | None):
        self.pack, self.chain, self.approver = pack, chain, approver

    def act(self, diag: Diagnosis) -> tuple[dict[str, Any] | None, str, str | None]:
        """Returns (remediation_record | None, approval_state, escalation_reason | None)."""
        rem = self.pack.remediations.get(diag.hypothesis)
        if rem is None:
            return None, "not_needed", "no automated remediation for this root cause"
        gate = gate_remediation(
            rem.risk,
            diag.confidence,
            rem.success_prob,
            rem.benefit,
            rem.harm,
            rem.cost,
            ambiguous=len(diag.prediction_set) > 1,
        )
        self.chain.append(
            {
                "event": "gate",
                "action": rem.name,
                "risk": rem.risk,
                "eu": round(gate.expected_utility, 4),
                "p": round(gate.p_success, 4),
                "reason": gate.reason,
            }
        )
        approval = "auto"
        if gate.requires_approval:
            ok = bool(self.approver(rem, diag)) if self.approver else False
            approval = "approved" if ok else "denied_or_pending"
            self.chain.append({"event": "approval", "action": rem.name, "result": approval})
            if not ok:
                return None, approval, f"approval required: {gate.reason}"
        try:
            result = rem.run()
        except Exception as exc:
            result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        self.chain.append({"event": "remediation", "action": rem.name, "result": str(result)[:200]})
        return (
            {
                "name": rem.name,
                "risk": rem.risk,
                "gate": gate.reason,
                "expected_utility": round(gate.expected_utility, 4),
                "result": result,
            },
            approval,
            None,
        )


class VerificationAuditor:
    def __init__(self, pack: DomainPack, chain: HashChain, max_reads: int = 12):
        self.pack, self.chain, self.max_reads = pack, chain, max_reads

    def verify(self) -> dict[str, Any]:
        sprt = SPRT(p0=0.5, p1=0.95)
        decision = "continue"
        while sprt.n < self.max_reads and decision == "continue":
            decision = sprt.update(bool(self.pack.verify()))
        out = {
            "healthy": decision == "accept_h1",
            "decision": decision,
            "reads": sprt.n,
            "llr": round(sprt.llr, 4),
        }
        self.chain.append({"event": "verification", **out})
        return out


class UniversalEngine:
    def __init__(
        self,
        pack: DomainPack,
        tau: float = 0.95,
        max_probes: int = 10,
        conformal: SplitConformal | None = None,
        approver: Approver | None = None,
        signing_key: bytes | None = None,
        brain: Brain | None = None,
        brain_weight: float = 0.3,
        max_remediation_retries: int = 1,
    ) -> None:
        self.pack, self.tau, self.max_probes = pack, tau, max_probes
        self.conformal, self.approver, self.signing_key = conformal, approver, signing_key
        self.brain, self.brain_weight = brain, brain_weight
        self.max_remediation_retries = max(0, max_remediation_retries)

    def solve(self) -> EngineResult:
        t0 = time.perf_counter()
        chain = HashChain(self.signing_key)
        chain.append({"event": "start", "domain": self.pack.name})
        diag = DiagnosticAgent(
            self.pack,
            chain,
            self.tau,
            self.max_probes,
            self.conformal,
            self.brain,
            self.brain_weight,
        ).run()
        rem_agent = RemediationAgent(self.pack, chain, self.approver)
        rem_rec: dict[str, Any] | None = None
        approval = "not_needed"
        reason: str | None = None
        verification = None
        status = "escalated"
        attempts = 0
        while attempts <= self.max_remediation_retries:
            rem_rec, approval, reason = rem_agent.act(diag)
            if rem_rec is None:
                break
            attempts += 1
            verification = VerificationAuditor(self.pack, chain).verify()
            if verification["healthy"]:
                status = "resolved"
                break
            if attempts <= self.max_remediation_retries and rem_rec["risk"] == "reversible_write":
                chain.append(
                    {
                        "event": "remediation_retry",
                        "action": rem_rec["name"],
                        "attempt": attempts + 1,
                    }
                )
                continue
            reason = "remediation applied but verification failed"
            break
        team = None
        if status == "escalated":
            team = self.pack.escalation.get(diag.hypothesis, self.pack.default_escalation)
        chain.append({"event": "receipt", "status": status, "hypothesis": diag.hypothesis})
        return EngineResult(
            status=status,
            domain=self.pack.name,
            diagnosis=diag,
            remediation=rem_rec,
            approval=approval,
            verification=verification,
            escalation_team=team,
            escalation_reason=reason if status == "escalated" else None,
            chain_root=chain.root(),
            chain_valid=chain.verify(),
            chain_signed=self.signing_key is not None,
            chain_length=len(chain.entries),
            events=[e.payload for e in chain.entries],
            wall_time_seconds=round(time.perf_counter() - t0, 4),
        )
