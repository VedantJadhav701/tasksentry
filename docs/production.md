# Production deployment blueprint

TaskSentry has two separate responsibilities:

1. **Harness engineering**: recognize one customer record, synthesize hypotheses,
   probes, remediations, escalation routes, and the live SOP graph.
2. **System integration**: connect those named probes and actions to an
   authenticated customer backend.

The first is universal. The second must be explicitly configured per customer
and domain; a model must never receive arbitrary shell access as a substitute.

## Universal onboarding

```python
from tasksentry.onboarding.pipeline import analyze, run

spec = analyze(one_record, llm=ollama_llm("beam:cloud"))
result = run(
    one_record, llm=ollama_llm("beam:cloud"), execution_mode="live", backend_id="customer-ran"
)
```

The backend is registered at service startup using `CallableBackend` or a
customer adapter implementing `DomainBackend`. It owns the allowlisted probe,
remediation, and independent verification functions. `simulation` is the safe
default for onboarding previews; `live` fails closed when no backend is
registered.

## 5G O-RAN/vRAN adapter requirements

Implement probes for the authoritative telemetry sources, including:

- DU management `ping6` and route/MTU evidence
- Kubernetes pod phase, readiness, restart count, and last termination reason
- Confd/NETCONF YANG state for `NRCELL_DU_*`, administrative state, DU-F1-C
- `notifmgr` alarm ordering and timestamps
- `timedatectl`, syncE, and IEEE 1588v2/PTP lock/holdover/offset
- O-RU M-Plane reachability and Open Fronthaul 7-2x link state

Each remediation must be a named API operation. Reversible writes may be
automated only after high-confidence evidence and positive expected utility;
system writes such as IPMI/BMC power cycles always require an external human
approval. Verification must read the post-state independently and may retry a
reversible action once before escalating.

## Model configuration

The onboarding UI defaults to `beam:cloud` through Ollama. Configure:

```text
OLLAMA_HOST=https://ollama.com
OLLAMA_API_KEY=<secret stored outside the repository>
```

Keep model credentials in a secret manager. Store only redacted model metadata
and signed execution receipts in TaskSentry.

## Operational controls

- Run the API behind TLS, authentication, tenant isolation, and RBAC.
- Use a per-tenant signing key from a secret manager; do not use a source-code
  default key.
- Persist audit chains to append-only storage and anchor chain roots externally.
- Run live adapters in a restricted worker/container with network policy.
- Export probe outcomes, remediation decisions, verification results, MTTR,
  escalation rate, false-remediation rate, and conformal coverage.
- Calibrate RCA likelihoods on held-out customer tickets; simulator results are
  regression tests, not production accuracy claims.
