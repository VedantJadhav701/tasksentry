# TaskSentry Advanced Overlay

Copy the contents of this zip's `tasksentry/` and `tests/` folders into your repo root.
It only **adds** files (no `__init__.py`, nothing of yours is overwritten). Two small fixes
to existing files are in `PATCHES.md`.

## What's new

| File | Purpose |
|---|---|
| `math/bayes_rca.py` | Bayesian root-cause posterior, expected-information-gain probe selection, log-linear pooling with a domain-trained model, Dirichlet priors |
| `math/conformal.py` | Split conformal prediction: root-cause *sets* with finite-sample coverage 1-alpha |
| `math/sequential.py` | Wald SPRT (verification with bounded error), CUSUM (drift) |
| `math/bandit.py` | Discounted Thompson sampling for cost-aware model-lane routing |
| `math/risk.py` | Expected-utility remediation gate, risk tiers, Wilson intervals |
| `math/hashchain.py` | Hash-chained, HMAC-signed audit log + Merkle root (tamper-evident) |
| `harness/domain.py` | `DomainPack`: the only thing you write to port the harness to a new domain |
| `harness/engine.py` | `UniversalEngine`: Diagnostic -> Remediation -> Verification Auditor |
| `telecom/pack.py` | Telecom pack wrapping your existing sandbox tools |
| `telecom/analytics.py` | Priors from the 3,813 tickets, analytics summary, noisy-sensor benchmark |
| `models/adaptive_router.py` | `SemanticModelRouter` + bandit exploration, `feedback()` |
| `console/api_v2.py` | `POST /api/chat/telecom/diagnose`, `GET /api/chat/telecom/analytics` |

## The math in one screen

- Posterior: P(h | o_1..t) ∝ P(h) ∏ P(o_i | h)
- Next probe: argmax_p [ H(P(h)) − E_o H(P(h | o)) ] / cost(p)
- Trained model pooling: P ∝ P_bayes^(1−w) · P_model^w
- Conformal set: C(x) = { h : 1 − P(h|x) ≤ q̂ }, q̂ = ⌈(n+1)(1−α)⌉/n quantile of calibration scores
- Remediation: EU = p·benefit − (1−p)·harm − cost, p = P(dx)·P(action works); system_write always needs approval; reversible writes auto-run only if P(dx) ≥ 0.85, EU > 0 and the conformal set is a singleton
- Verification: SPRT, LLR += ln(p1/p0) per healthy read; accept at ln((1−β)/α)
- Audit: h_i = SHA256(h_{i−1} ‖ canonical(event_i)), sig_i = HMAC(key, h_i)

## Making it universal

```python
from tasksentry.harness.domain import DomainPack, Remediation
from tasksentry.math.bayes_rca import Probe
from tasksentry.harness.engine import UniversalEngine

pack = DomainPack(
    name="my-domain",
    priors=...,
    probes=[Probe("p1", {"h1": 0.9, "h2": 0.1}, cost=1)],
    run_probe=lambda name: ...,
    verify=lambda: ...,
    remediations={...},
)
engine = UniversalEngine(pack, brain=my_domain_model_fn, conformal=fitted_conformal)
```

`brain(ctx) -> {"probs": {hyp: p}, "analysis": str}`. A domain-trained model (e.g. your `telco:latest`)
returns hypothesis probabilities; they are pooled with the Bayesian posterior, and a failing brain never blocks diagnosis.

## Honest limits

- Sensitivities in `telecom/pack.py` are expert priors. Re-estimate them from labelled tickets before trusting confidences.
- Conformal coverage is only guaranteed if calibration data resembles production. The bundled benchmark calibrates on simulator output, so it is a regression test, not field accuracy.
- Run tests with `pytest tests/test_advanced.py` inside your repo (it uses your real `tools.py`).

---

# v2: Universal onboarding + Web Console

## Upload ONE record -> full harness
`tasksentry/onboarding/`
- `infer.py` recognizes the record format (JSON / JSONL / ChatML, steps found anywhere in the record), pulls entities (gnb_id, du_id, data center...), the failure label, and each step's commands, PASS/FAIL expectations, subissue, actions, escalation, and "X to Y" failure mappings. If recognition confidence is low and an LLM is supplied, the LLM proposes a field mapping that is **validated against the record** before use.
- `synth.py` turns the profile into a `HarnessSpec`: root-cause hypotheses, one probe per SOP step (step 5 splits into 4 probes from its mapping clause), remediations with risk tiers, documented escalations, and priors boosted from the label hint. Sensitivities are heuristic (0.92 / 0.04). Optional LLM refinement (Ollama `beam:cloud`) can adjust sensitivities and can only **raise** a remediation's risk tier, never lower it. If the cloud model is unreachable, the deterministic spec is used and a note is recorded.
- `pipeline.py`: `analyze(record)` and `run(record)`; `run` executes the governed engine on a **simulated backend** (clearly labelled in the UI). To go live, replace `SimulatedBackend` with callables that hit your real systems.
- `api.py`: `POST /api/onboard/analyze`, `POST /api/onboard/run` (include the router in your FastAPI app).

## Web console (iOS style, live SOP graph)
`webapp/`: `index.html`, `style.css`, `app.js`, `server.py`, `sample_ticket.json`.
Run from the repo/zip root:
```
pip install fastapi uvicorn pydantic
PYTHONPATH=. python -m uvicorn webapp.server:app --port 8080
# open http://localhost:8080
```
Tabs: **Onboard** (paste/upload a record, pick `beam:cloud`, sensor noise, pre-approval), **Live Run** (animated SOP graph: nodes light up red/green as probes run, numbered in execution order, unused steps dim as "skipped (low info gain)"; live posterior bars; terminal stream; signed-audit result card), **Harness** (generated hypotheses, probes, remediations, notes).
The run is computed server-side and then replayed with animation, so the graph shows the real execution order and posterior after every probe.

Cloud model: start Ollama locally with access to `beam:cloud` (set `OLLAMA_HOST` if not on 127.0.0.1:11434). I could not call beam:cloud from here, so LLM paths were tested with stub models only.
The UI was syntax-checked and its API exercised, but not visually checked in a browser, so expect some CSS polish.
