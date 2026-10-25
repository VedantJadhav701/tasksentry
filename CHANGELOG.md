# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-26

### Added
- Budget-native agent harness and control plane for running AI agents with deterministic cost, latency, and reliability control.
- Task contracts with verifier-backed success criteria, intermediate milestones, budget limits, and safety rules.
- Multi-dimensional budget meter tracking tokens, cost (USD), wall-clock time, and tool calls with hard and soft limit policies.
- Pricing catalog with default per-token pricing and custom pricing overrides.
- Tool registry, Pydantic argument schema validation, risk classification, and allowlists.
- Process-isolated and in-process execution sandboxes with enforced per-tool timeouts.
- Canonical task state hashing `s_t = (g, M_t, K_t, W_t)` and action fingerprinting including state hash to avoid volatile progress noise.
- Agent Progress Gain (`APG`), rolling `WindowGain`, exponential moving average (`EMA`), and canonical loop stop/escalation policies.
- Hypothesis belief tracking with Bayesian entropy reduction and labelled proxy fallback.
- Verification gate preventing premature completion claims through independent, verifier-backed criteria checks.
- Recovery engine providing tiered failure recovery (backoff retry, forced replan, context compaction, human escalation).
- CASE agent runtime loop (`Contract -> Planner -> ActionGate -> Executor`).
- Agent and model registry supporting declarative YAML configurations and custom Python callables.
- Persistent SQLite and thread-safe in-memory task receipt stores.
- Top-level Python SDK (`AgentTask`, `Budget`, `ToolGovernor`, `budget` context manager, `@tool` decorator).
- OpenAI-compatible model client integration with automatic ambient budget meter charging.
- Command-line interface (`tasksentry`) with subcommands: `demo`, `run`, `tasks`, `task`, `receipt`, `benchmark`, `ollama-health`, `dashboard`, and `benchmark-report`.
- TaskSentryBench v0.1 with offline regression track (26 tasks across 10 families) and local Ollama track.
- Local developer dashboard powered by FastAPI and modern vanilla JavaScript on `http://127.0.0.1:8321`.

### Security
- In-process execution mode is not a security boundary; runs with host process permissions.
- Process-isolated mode executes tools in sub-processes with picklable arguments and timeout termination.
- Local dashboard binds strictly to `127.0.0.1` by default.
