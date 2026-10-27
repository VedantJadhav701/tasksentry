# Domain DSLM + Governed Autonomy Report

## Status

PASS for the offline/deterministic domain milestones M1-M7. The existing
`tasksentry_phase7` directory was preserved; implementation continued in the
active repository root because the root already contained the telecom,
onboarding, and current test tree.

## Implemented

- **M1:** `src/tasksentry/domain/schema.py`, `ingest.py`, `redact.py`, and
  `split.py`: canonical trajectories, JSON/JSONL/CSV/ChatML recognition,
  optional recognizer protocol disabled by default, tenant-local redaction,
  stable deduplication, and time/customer leakage-safe splits.
- **M2:** `domain/catalog.py`: versioned typed command catalogs, structured
  validation errors, argv-only rendering, preconditions, tenant scope,
  rollback links, human-reviewable drafts, and ToolRegistry/ToolGovernor
  integration.
- **M3:** `domain/datasets.py`: deterministic SFT, preference, refusal, and
  format-repair JSONL exports plus dataset cards. Added CLI commands:
  `domain ingest`, `domain catalog`, and `domain export`.
- **M4:** `domain/autonomy.py`: L0-L3 policy decisions, shadow proposals,
  kill switch, rate/blast-radius caps, Wilson promotion gates, and optional
  fail-closed ToolGovernor policy callback. Added Console autonomy/review/
  proposal endpoints.
- **M5:** `domain/replay.py`: deterministic simulated backend, harness-only
  baseline, pluggable prediction protocol, root-cause/escalation/calibration/
  safety/validity metrics, confidence intervals, JSON/Markdown reports, and
  regression comparison. Added `domain eval` CLI command.
- **M6:** Added Console Governance tab and safe DOM rendering for autonomy
  levels, approvals, harness reviews, shadow proposals, and kill switch.
- **M7:** Added `docs/domain.md`, architecture/security/README updates,
  cloud recognition opt-in with tenant-local redaction, and
  `examples/domain_5g_demo.py`.

## Final verification

Real command output:

```text
$ py -3.11 -m pytest -q
446 passed, 1 warning in 14.20s

$ py -3.11 -m ruff check .
All checks passed!

$ py -3.11 -m ruff format --check .
351 files already formatted

$ py -3.11 -m mypy src/tasksentry
Success: no issues found in 105 source files
```

Node smoke checks also passed for `webapp/app.js` and the existing Console
`console.js`. The repository gained 111 tests over the 335-test root baseline,
exceeding the 85-test requirement.

## Replay baseline

The offline 5G demo evaluated one simulated ticket (`n=1`) using the
harness-only model:

- root-cause top-1: `1.0`
- root-cause top-3: `1.0`
- format validity: `1.0`
- tool-call validity: `1.0`
- unsafe-action rate: `0.0`
- probe efficiency: `1.0`
- simulated shadow proposals: `6`

These are a smoke baseline, not a production performance claim. The sample is
fully simulated and too small for promotion.

## Known limitations

- Replay uses recorded observations and does not prove behavior against live
  network systems.
- The harness-only baseline is not a fine-tuned DSLM; no training pipeline or
  constrained decoding is included yet.
- Hypothesis quality and labels depend on source data and human verification.
- Real customer backends, vault credential injection, external audit anchoring,
  and multi-tenant hosted deployment remain future work.
- Local Console governance state is process-local; review endpoints record
  decisions but do not replace a durable customer workflow.

## Next phase

Build the training pipeline (LoRA SFT followed by preference tuning), model
registry and promotion records, constrained JSON decoding, durable tenant
policy storage, and real backend adapters behind the typed catalog.

---

# Phase 6 Report: Open-Source Release Readiness (v0.1.0)

## Status
PASS

## Release Readiness

TaskSentry v0.1.0 is fully verified and prepared for public open-source release:
- **Core Harness & Progress Math**: Completed and verified (Phases 1-3).
- **Public SDK, Storage & CLI**: Completed and verified (Phase 4).
- **TaskSentryBench v0.1 & Local Dashboard**: Completed and verified (Phase 5).
- **Packaging, CI Workflows & Documentation**: Completed and verified (Phase 6).
- **Quality Gates**: 247 tests passing, ruff clean, ruff format clean, mypy strict clean, package builds cleanly (`.tar.gz` and `.whl`).

---

## Documentation

The following documentation files have been written, validated, and linked:
1. `README.md`: Project landing page with architecture diagram, core concepts, quickstart, SDK examples, CLI, benchmarks, limitations, and roadmap.
2. `LICENSE`: Apache License 2.0.
3. `NOTICE`: Copyright and community attribution notice.
4. `CONTRIBUTING.md`: Development setup, architectural rules, code of conduct reference, and PR checklist.
5. `CODE_OF_CONDUCT.md`: Contributor Covenant Code of Conduct.
6. `SECURITY.md`: Vulnerability reporting process, sandbox trust boundaries, write approval rules, and local dashboard security.
7. `CHANGELOG.md`: Detailed record of all features, enhancements, and security notices for v0.1.0.
8. `RELEASE.md`: Step-by-step checklist and procedures for tagging GitHub releases and future PyPI publications.
9. `docs/architecture.md`: Detailed system architecture, component responsibilities, and runtime loop data flow.
10. `docs/mathematics.md`: Mathematical foundations: canonical state hashing, action fingerprints, Bayesian belief update, information gain, APG formula, WindowGain, EMA, stop policy, and benchmark metrics.
11. `docs/quickstart.md`: Step-by-step installation, demo run, first task creation, and dashboard launch.
12. `docs/benchmark.md`: TaskSentryBench v0.1 specification (offline regression track vs. local Ollama track, 26 tasks across 10 families, 6 systems compared, and metrics formulas).
13. `docs/ollama.md`: Local Ollama setup, model pull guide (`llama3.2:1b`, `qwen3:4b-instruct-2507-q4_K_M`), health checks, and caveats.
14. `docs/configuration.md`: Environment variables, YAML configuration, pricing tables, and policy configuration.
15. `docs/cli.md`: Comprehensive CLI reference covering all 9 commands and exit codes.
16. `docs/dashboard.md`: Local dashboard architecture, views, and REST API endpoints.
17. `docs/security.md`: In-depth security analysis of sandbox isolation, tool risk allowlists, and write approvals.
18. `docs/roadmap.md`: Near-term (v0.2.0 - v0.3.0) and long-term (v0.4.0+) feature roadmap.
19. `docs/release.md`: Release engineering guide for v0.1.0.
20. `examples/`:
    - `examples/wrap_existing_agent.py`: Ambient budget tracking wrapper demo.
    - `examples/coding_agent_demo.py`: Autonomous coding repair task demo.
    - `examples/research_agent_demo.py`: Research task with milestone verifications.
    - `examples/dashboard_demo.py`: Programmatic dashboard API verification.
    - `examples/ollama_benchmark_demo.py`: Local Ollama health and benchmark execution demo.

---

## Packaging

Editable installation with optional extras:
```bash
pip install -e ".[dev,dashboard,ollama]"
```

Package build output (`python -m build`):
```
Successfully built tasksentry-0.1.0.tar.gz and tasksentry-0.1.0-py3-none-any.whl
```

Package metadata details:
- Name: `tasksentry`
- Version: `0.1.0`
- License: `Apache-2.0`
- Python: `>=3.11`
- Includes typed marker: `src/tasksentry/py.typed`
- Extras: `dev`, `dashboard`, `ollama`, `openai`, `benchmark`
- CLI Entrypoint: `tasksentry = tasksentry.cli:main`

---

## Continuous Integration & Release Workflows

1. **`.github/workflows/ci.yml`**:
   - Matrix testing across Python 3.11 and Python 3.12.
   - Linting with `ruff check .` and formatting check with `ruff format --check .`.
   - Strict static type analysis with `mypy src/tasksentry`.
   - Full unit and integration test suite with `pytest -q --cov`.
   - Package build verification with `python -m build` and `twine check dist/*`.
   - Offline benchmark smoke test: `python -m tasksentry.benchmark.runner --suite offline-v0.1 --output reports/ci-benchmark.json`.
   - Runs zero cloud API calls and requires zero external API keys in CI.

2. **`.github/workflows/release.yml`**:
   - Triggers exclusively on `v*.*.*` tags.
   - Verifies tests, linters, type checks, and package builds.
   - Attaches `.tar.gz`, `.whl`, and Markdown benchmark reports directly to the GitHub Release.
   - Requires manual environment approval for future PyPI publishing.

---

## Security Model & Limitations

1. **In-Process Mode**: Designed for local development and unit tests. Does not isolate memory or host OS permissions.
2. **Process-Isolated Mode**: Executes tools in isolated sub-processes with wall-clock timeout enforcement. Protects against interpreter crashes and hangs, but is not an OS container or security sandbox.
3. **Tool Approvals**: Tasks can mandate human authorization callbacks for `write` and `destructive` tools via `require_approval_for_writes`.
4. **Local Dashboard**: Strictly binds to `127.0.0.1:8321` by default with zero external telemetry. Not intended for direct internet exposure without an authenticating reverse proxy.

---

## Test Results

Actual output of `python -m pytest -q`:
```
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 87%]
...............................                                          [100%]
247 passed in 11.53s
```

---

## Lint and Type Check Results

Actual output of `ruff check .`:
```
All checks passed!
```

Actual output of `ruff format --check .`:
```
126 files already formatted
```

Actual output of `mypy src/tasksentry`:
```
Success: no issues found in 59 source files
```

---

## Benchmark Smoke Test

Command:
```bash
python -m tasksentry.benchmark.runner --suite offline-v0.1 --output reports/release-smoke.json
```

Output:
```
Starting TaskSentryBench v0.1: suite='offline-v0.1', seed=42
Benchmark completed successfully at 2026-10-25T19:11:41.239613+00:00
JSON report: reports/release-smoke.json
Markdown report: reports/release-smoke.md
```

Aggregate Results:
- `tasksentry_case`: 100.0% success rate, 143.1 tokens/success, 1.2 tool calls/task, 0.010s p95 latency, 100.0% budget compliance.
- 26 tasks verified across all 10 failure-mode families.

---

## Known Limitations

1. **Offline Benchmark**: The offline regression suite (`offline-v0.1`) tests mathematical invariants and loop controller mechanics with deterministic scripted agents; it does not measure open-ended general intelligence on unconstrained prompts.
2. **Local Ollama Track**: Benchmark latency and throughput depend on host GPU VRAM and local quantization formats.
3. **Local-Only Dashboard**: The dashboard is a developer inspection tool binding to loopback; multi-tenant access and hosted deployments require external reverse proxies.
4. **PyPI Publishing**: Release workflow builds distribution packages and attaches them to GitHub releases; PyPI uploading requires manual maintainer approval.

---

## Next Steps After v0.1.0

1. **Real-Model Benchmark Publication**: Community benchmark matrix tracking open-weights models (`qwen2.5`, `llama3.2`, `gemma2`) across GPU hardware.
2. **Framework Adapters**: First-class drop-in middleware for LangGraph StateGraphs, CrewAI agents, and AutoGen teams.
3. **Containerized Sandboxing**: Docker and Podman execution drivers for untrusted code execution.
4. **Policy Learning**: Empirical APG weight tuning based on task category.
5. **Advanced Context Compaction**: Checkpointed state compaction and rollback capabilities.


---

# Phase 7 Report: TaskSentry Console & Semantic Model Routing

## Status
PASS

## Highlights
- **Chat-First Console**: Full interactive agent console with live chat, Server-Sent Events (SSE) streaming, and WebSocket support.
- **Semantic Model Routing**: Real-time routing across local Ollama models with Fast Routine (`qwen2.5:3b`, `llama3.2:1b`, `gemma2:2b`) and Deep Reasoning (`qwen3:4b-instruct-2507-q4_K_M`, `ornith:latest`) lanes.
- **Auditable Explanations**: Every model selection reports rationale, complexity signals, stagnant steps count, open failures count, and fallbacks.
- **Human-in-the-Loop Approvals**: Write-capable tools (`write_text_file`, `run_command`, etc.) pause the agent and prompt the user to approve or reject actions.
- **Router Playground**: Interactive multi-lane prompt comparison testing routine, reasoning, and routed decisions.
- **Telemetry & Verification**: Real-time budget burn-down meters, verification gate status, loop controller metrics, and instant JSON receipt downloads.
- **Test Suite**: 298 total passing tests (including 46 new console tests covering chat, routing, approvals, streaming, receipts, and model health).
