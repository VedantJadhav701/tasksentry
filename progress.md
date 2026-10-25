# TaskSentry: Comprehensive Technical Progress Report

**Document Date:** October 26, 2026  
**Repository:** [tasksentry](https://github.com/VedantJadhav701/tasksentry)  
**Current Version:** `v0.1.0` (with Phase 7 TaskSentry Console)  
**Verified Test Count:** **298 Tests Passing**  
**Code Quality Status:** `ruff` clean, `ruff format` clean, `mypy` strict clean  

---

## 1. Executive Summary

Autonomous AI agents in real-world deployment suffer from three critical operational vulnerabilities:
1. **Runaway Billing & Infinite Loops**: Repetitive tool calling or self-correction loops that rapidly consume API budgets without making progress.
2. **Premature Victory**: Models declaring "Goal achieved!" in their prompt output while failing underlying unit tests, asserts, or schema requirements.
3. **Execution Deadlocks**: Repeated execution of identical failing actions due to lack of memory and progress tracking.

**TaskSentry** is an open-source, budget-native agent harness and control plane for task-level cost, latency, reliability, and safety control. It sits between user-facing agent frameworks (such as LangGraph, CrewAI, AutoGen, or custom agents) and backend tools/LLMs, enforcing deterministic verification, mathematical progress tracking, and ambient budget governance.

---

## 2. Evolution & Detailed Phase Breakdown

```
+-------------------------------------------------------------------------------------------------+
|                                    TASKSENTRY EVOLUTION                                         |
+-------------------------------------------------------------------------------------------------+
| Phase 1: Core Math & State Ledger       --> Canonical State, APG, Belief Tracking, Loop Detection|
| Phase 2: Budgeting & Tool Governance    --> Pricing Tables, Schema Validation, Process Sandbox  |
| Phase 3: CASE Runtime & Recovery        --> ActionGate, VerificationGate, RecoveryEngine, Loop  |
| Phase 4: Public SDK & Persistent Store  --> AgentTask, SQLite Store, CLI, Ambient budget()       |
| Phase 5: TaskSentryBench & Dashboard    --> 26-task Benchmark Suite, FastAPI Local Dashboard    |
| Phase 6: Production Packaging & Release --> pyproject build, CI Workflows, Full Documentation   |
| Live Ollama & Semantic Model Router     --> Native Ollama Tools, Fast/Deep Routing Lanes        |
| Phase 7: Chat-First TaskSentry Console  --> Live Chat, SSE Stream, Approvals, Router Playground |
+-------------------------------------------------------------------------------------------------+
```

---

### Phase 1: Canonical State, Information Gain & APG Loop Controller

- **Canonical State Representation (`CanonicalState`)**:
  - Defined volatile-free task state: $s_t = (g, M_t, K_t, W_t)$ where $g$ is goal, $M_t$ is completed milestones, $K_t$ is knowledge facts, and $W_t$ is durable world state.
  - Eliminated timestamps, ephemeral logs, and counters from hashing to ensure deterministic canonical identity across steps.
- **Action Fingerprinting (`action_fingerprint`)**:
  - Deterministic canonical serialization of tool actions and argument dictionaries using SHA-256.
- **Bayesian Information Gain & Hypothesis Belief Tracking**:
  - Discrete Bayesian update formulation computing entropy reduction:
    $$IG(a_t) = H(P_{t-1}(\Theta)) - H(P_t(\Theta))$$
  - Provides a bounded proxy metric when explicit hypothesis sets are absent.
- **Agent Progress Gain (`APG`)**:
  - Mathematical progress metric combining milestone completion, information gain, open error reduction, and action cost penalties:
    $$APG(a_t) = w_m \Delta M + w_{ig} IG(a_t) + w_{err} \Delta E - w_{cost} C(a_t)$$
- **Rolling WindowGain & EMA Progress Tracker**:
  - Rolling window evaluation ($W=5$) and exponential moving average ($\alpha=0.3$) detecting stagnant or looping execution loops before catastrophic token burn occurs.

---

### Phase 2: Budgeting, Pricing Tables, Tool Registry & Isolation Sandbox

- **Multi-Dimensional Budgeting (`Budget`, `BudgetLimits`)**:
  - Tracks and enforces 5 dimensions: input tokens, output tokens, cost in USD, tool calls, and wall-clock execution seconds.
  - Hard limit enforcement (raises `BudgetExceededError`) and soft warnings (emits `BUDGET_WARNING` at 80% threshold).
- **Model Pricing Table (`PricingTable`, `ModelPricing`)**:
  - Configurable pricing per 1M tokens (e.g., GPT-4o, Claude 3.5 Sonnet, Llama 3, local free models).
  - Exact token calculation and prospective cost projection.
- **Tool Registry & JSON-Schema Validation (`ToolRegistry`, `@tool`)**:
  - Pydantic v2 input validation with automatic JSON schema generation.
  - Risk classification: `read`, `reversible_write`, `irreversible_write`, `system_write`.
- **Tool Governor (`ToolGovernor`)**:
  - Repetition blocking: detects and halts duplicate action attempts.
  - Governor charges budget meters only upon actual execution attempts (never for blocked calls).
- **Process-Isolated Execution Sandbox (`Sandbox`)**:
  - Dual-mode execution:
    1. `in_process`: Fast in-memory execution for trusted read operations.
    2. `process_isolated`: Subprocess isolation via Python `multiprocessing` with wall-clock timeout termination.

---

### Phase 3: CASE Agent Runtime Loop, Verification & Recovery

- **The CASE Runtime Loop (`CASERuntime`)**:
  - Structured iterative control loop: `Contract -> Planner -> ActionGate -> Executor`.
- **Action Gate (`ActionGate`)**:
  - Pre-execution validation evaluating whether an action is permitted by tool risk, governor duplicates, and remaining budget.
- **Verification Gate (`VerificationGate`)**:
  - Verifies objective acceptance criteria using deterministic verifiers:
    - `file_exists`, `regex_match`, `command_exit_code`, `pytest`, `json_schema`, `numeric_range`, `python_assert`, `artifact_exists`.
  - Prohibits premature self-declaration of completion: completion claims require all required criteria to pass.
- **Hierarchical Recovery Engine (`RecoveryEngine`)**:
  - 4-tiered recovery ladder:
    1. `CONTINUE`: Exponential backoff on transient errors.
    2. `FORCE_REPLAN`: Immediate replanning on disallowed actions or verification rejections.
    3. `COMPACT_CONTEXT`: Truncates redundant history and retains essential facts.
    4. `ESCALATE`: Human escalation after 3 consecutive blocked actions or loop deadlocks.
- **Stop Conditions Engine (`evaluate_stop_conditions`)**:
  - Evaluates deadline expiration, budget exhaustion, stagnant loops, and goal satisfaction.

---

### Phase 4: Public SDK Surface, Agent Registry, Storage & CLI

- **High-Level SDK Surface (`AgentTask`)**:
  - Clean declarative API to configure, bind, and execute tasks:
    ```python
    task = AgentTask(
        goal="Fix test regression in auth module",
        success_criteria=[{"id": "pytest_pass", "verifier": "pytest"}],
        max_cost_usd=0.25,
        max_tokens=20000,
    )
    receipt = task.run(agent="semantic-router")
    ```
- **Ambient Context Manager (`budget()`)**:
  - Wrap any third-party framework (LangGraph, CrewAI, AutoGen) with zero intrusive code changes:
    ```python
    with budget(max_tokens=4000, max_cost_usd=0.05) as b:
        run_my_external_agent()
    receipt = b.receipt()
    ```
- **Persistent Storage (`SQLiteReceiptStore`, `InMemoryReceiptStore`)**:
  - Durable persistence of contracts, receipts, events, and audit logs into SQLite (`tasksentry.db`).
- **OpenAI-Compatible Client (`OpenAICompatibleClient`) & Agent Registry (`AgentRegistry`)**:
  - Universal provider support for local servers (Ollama, vLLM, LM Studio) and remote providers.
- **CLI Commands (`tasksentry`)**:
  - `demo`, `run`, `tasks`, `task`, `receipt`, `benchmark`, `ollama-health`, `dashboard`.

---

### Phase 5: TaskSentryBench v0.1 & Local Developer Dashboard

- **TaskSentryBench v0.1**:
  - Comprehensive benchmarking framework comparing 6 harness systems across 26 tasks in 10 failure-mode families:
    1. `react_baseline` (unconstrained ReAct loop)
    2. `baseline_safeguards` (ReAct + step cap + duplicate blocking)
    3. `baseline_reflection` (ReAct + prompt reflection on error)
    4. `tasksentry_case` (Full CASE harness with APG and verification gates)
    5. `case_ablation_no_apg` (CASE without APG controller)
    6. `case_ablation_no_verification` (CASE without objective gates)
  - Dual tracks:
    - **Offline Track**: Deterministic mock agents testing mathematical loop invariants with 0 API cost.
    - **Local Ollama Track**: Real inference benchmarks over local open-weights models.
- **Local Dashboard (`tasksentry dashboard`)**:
  - Local FastAPI web application serving task history, execution logs, and benchmark reports at `http://127.0.0.1:8321`.

---

### Phase 6: Production Packaging, CI/CD & Open-Source Release

- **Standard Packaging**:
  - Built distributions: `tasksentry-0.1.0.tar.gz` and `tasksentry-0.1.0-py3-none-any.whl`.
  - Configured optional dependency extras: `dev`, `dashboard`, `ollama`, `openai`, `benchmark`.
- **Automated CI Workflows (`.github/workflows/ci.yml`, `release.yml`)**:
  - Automated matrix testing on Python 3.11 and 3.12.
  - Strict type checking (`mypy`), linting (`ruff`), and benchmark regression smoke tests.
- **Documentation Suite**:
  - Authored comprehensive documentation: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `NOTICE`, `docs/architecture.md`, `docs/mathematics.md`, `docs/quickstart.md`, `docs/benchmark.md`, `docs/ollama.md`, `docs/cli.md`, `docs/dashboard.md`, `docs/security.md`, and `docs/roadmap.md`.

---

### Live Ollama Integration & Semantic Model Routing

- **Live Ollama LLM Connection**:
  - Tested and integrated with locally installed models:
    - `qwen3:4b-instruct-2507-q4_K_M`
    - `qwen2.5:3b`
    - `llama3.2:1b`
    - `gemma2:2b`
    - `ornith:latest`
    - `beam:cloud`
- **Context Window OOM Resolution**:
  - Identified that default context allocations in Ollama for `qwen3:4b-instruct-2507-q4_K_M` trigger a 38GB KV cache allocation and HTTP 500 crashes.
  - Automatically configured safe context window limits (`options: {"num_ctx": 4096}`) across all `qwen3` calls.
- **`SemanticModelRouter` (`src/tasksentry/models/router.py`)**:
  - Dynamically routes requests based on real-time task signals:
    - **Fast Routine Lane**: `qwen2.5:3b` / `llama3.2:1b` (tool arguments, reading state, quick inspection).
    - **Deep Reasoning Lane**: `qwen3:4b-instruct-2507-q4_K_M` / `ornith:latest` (planning, failure analysis, root-cause diagnosis, recovery).
  - Automated fallback: gracefully switches to secondary models if a model is offline or returns an error.
- **`LLMAgent` (`src/tasksentry/harness/agent.py`)**:
  - Converts registered tools to OpenAI-compatible function calling schemas.
  - Parses native structured `tool_calls` and markdown JSON blocks.
  - Tracks token usage and charges the task budget directly.

---

### Phase 7: TaskSentry Console (Chat-First Agent Control Plane)

- **Chat-First UI (`src/tasksentry/console/static/`)**:
  - Built with vanilla HTML5/CSS3/JavaScript (dark theme, zero npm build steps).
  - **Left Sidebar**: Task creation trigger, historical task contracts, status pills.
  - **Center Workspace**:
    - Real-time chat stream with token-by-token reasoning output.
    - Tool-call cards with input arguments and execution observations.
    - Interactive human-in-the-loop approval cards for write actions.
  - **Right Sidebar (Live Inspector)**:
    - Model route badge (`⚡ ROUTINE` vs `🧠 REASONING`), selected model, and routing rationale.
    - Visual budget burn-down meters for tokens, tool calls, and wall-time.
    - Objective verification gate status (PASSED / PENDING).
    - Real-time event timeline and instant JSON receipt download.
- **Router Comparison Playground**:
  - Compare any prompt side-by-side across the Routine lane, Reasoning lane, and Routed decision with live latency and token accounting.
- **Ollama Model Mesh Health**:
  - Real-time server connectivity, latency, context windows, and recommended model roles.
- **Console REST & Streaming API (`src/tasksentry/console/api.py`, `sockets.py`)**:
  - Endpoints: `POST /api/chat/tasks`, `GET /api/chat/tasks/{task_id}/stream` (SSE), `POST /approve`, `POST /reject`, `POST /stop`, `GET /receipt`, `GET /models`, `GET /routing/{task_id}`, `POST /playground/compare`.
- **Human-in-the-Loop Approvals (`ApprovalManager`)**:
  - Thread-safe pause-and-resume gate for unsafe write actions (`write_text_file`, `run_command`).
- **CLI Subcommand**:
  - `python -m tasksentry.cli console --host 127.0.0.1 --port 8321`.

---

## 3. Architecture & Data Flow

```
                                +---------------------------------------------+
                                |             TaskSentry Console              |
                                |  (Chat UI, SSE Stream, Routing Inspector)   |
                                +---------------------------------------------+
                                                       │
                                               WebSocket / SSE
                                                       │
                                +---------------------------------------------+
                                |                TaskSentry API               |
                                |  (/api/chat/tasks, /stream, /approve, etc.) |
                                +---------------------------------------------+
                                                       │
                                                       v
                                +---------------------------------------------+
                                |              CASERuntime Loop               |
                                |      (Planner -> ActionGate -> Executor)    |
                                +---------------------------------------------+
                                                       │
                                                       v
                                +---------------------------------------------+
                                |            SemanticModelRouter              |
                                |     (Signal Engine & Lane Classifier)       |
                                +---------------------------------------------+
                                       /                               \
                                      v                                 v
                             +------------------+             +--------------------+
                             |   Routine Lane   |             |   Reasoning Lane   |
                             |   (Fast Tools)   |             | (Planning & Recov) |
                             |    qwen2.5:3b    |             | qwen3:4b / ornith  |
                             +------------------+             +--------------------+
                                      \                                 /
                                       v                               v
                                +---------------------------------------------+
                                |           Local Ollama LLM Mesh             |
                                |            (http://127.0.0.1:11434)         |
                                +---------------------------------------------+
```

---

## 4. Quality Gates & Test Verification

All quality gates pass without warnings or regressions:

| Quality Gate | Command | Status | Details |
| :--- | :--- | :--- | :--- |
| **Unit & Integration Tests** | `python -m pytest -q` | **PASS** | **298 passed** in 15.10s |
| **Code Style & Linting** | `ruff check .` | **PASS** | All checks passed cleanly |
| **Code Formatting** | `ruff format --check .` | **PASS** | 124 files formatted |
| **Static Type Analysis** | `mypy src/tasksentry` | **PASS** | Strict clean across 68 files |

---

## 5. Directory & File Inventory

```text
tasksentry/
├── agents/                       # Agent and policy YAML configurations
│   ├── agents.yaml
│   └── policies.yaml
├── configs/                      # Pricing tables and runner configs
│   └── pricing_table.json
├── docs/                         # Full documentation suite
│   ├── architecture.md
│   ├── benchmark.md
│   ├── cli.md
│   ├── configuration.md
│   ├── console.md                # Phase 7 Console documentation
│   ├── dashboard.md
│   ├── mathematics.md
│   ├── ollama.md
│   ├── quickstart.md
│   ├── release.md
│   ├── roadmap.md
│   └── security.md
├── examples/                     # Ready-to-run demo scripts
│   ├── coding_agent_demo.py
│   ├── dashboard_demo.py
│   ├── live_semantic_agent.py    # Live Ollama semantic routing script
│   ├── ollama_benchmark_demo.py
│   ├── research_agent_demo.py
│   └── wrap_existing_agent.py
├── src/tasksentry/               # Core library
│   ├── benchmark/                # TaskSentryBench suite & metrics
│   ├── budget/                   # Budget tracking, meters & pricing
│   ├── console/                  # Phase 7 Chat-First Console & SSE
│   │   ├── api.py
│   │   ├── app.py
│   │   ├── approvals.py
│   │   ├── chat.py
│   │   ├── routing.py
│   │   ├── runs.py
│   │   ├── sockets.py
│   │   └── static/               # Vanilla frontend assets
│   ├── core/                     # TaskContract, CanonicalState, CASERuntime, Receipt
│   ├── dashboard/                # Analytics dashboard
│   ├── harness/                  # Planner, ActionGate, Executor, Recovery, LLMAgent
│   ├── math/                     # APG, Information Gain, ProgressTracker
│   ├── models/                   # Ollama, SemanticModelRouter, OpenAICompat, Registry
│   ├── storage/                  # SQLite & In-Memory receipt stores
│   └── tools/                    # Tool registry, Governor, Sandbox, Builtin tools
└── tests/                        # 298 Automated tests
    ├── test_action_gate.py
    ├── test_agent_registry.py
    ├── test_benchmark.py
    ├── test_budget.py
    ├── test_cli.py
    ├── test_console_api.py       # Phase 7 Console API tests
    ├── test_console_approvals.py # Phase 7 Approvals tests
    ├── test_console_chat.py      # Phase 7 Chat session tests
    ├── test_console_models.py    # Phase 7 Model health tests
    ├── test_console_receipts.py  # Phase 7 Receipts tests
    ├── test_console_routing.py   # Phase 7 Routing tests
    ├── test_console_streaming.py # Phase 7 SSE streaming tests
    ├── test_information_gain.py
    ├── test_ollama_client.py
    ├── test_progress.py
    ├── test_router_and_llm_agent.py
    ├── test_tool_governor.py
    └── test_verification.py
```

---

## 6. How to Run TaskSentry

### 1. Launch the Chat-First Console
```powershell
python -m tasksentry.cli console --host 127.0.0.1 --port 8321
```
Open **`http://127.0.0.1:8321`** to chat with local Ollama agents, inspect routing lanes, approve write operations, and download task receipts.

### 2. Run the Live Demo with Semantic Routing via CLI
```powershell
python -m tasksentry.cli demo --live --routine-model qwen2.5:3b --reasoning-model qwen3:4b-instruct-2507-q4_K_M
```

### 3. Run the Live Python SDK Example
```powershell
python examples/live_semantic_agent.py
```

### 4. Inspect Stored Tasks & Auditable Receipts
```powershell
python -m tasksentry.cli tasks
python -m tasksentry.cli receipt <TASK_ID>
```

### 5. Run Full Test Suite
```powershell
python -m pytest -q
ruff check .
ruff format --check .
mypy src/tasksentry
```

---

## 7. Next Roadmap Items (Post v0.1.0)

1. **Framework Adapters**: First-class drop-in middleware for LangGraph `StateGraph`, CrewAI, and AutoGen.
2. **Containerized Sandboxing**: Docker and Podman sandboxing drivers for untrusted code execution.
3. **Adaptive APG Weights**: Machine-learned parameter tuning for progress weights across domain-specific task types.
4. **State Checkpoint Rollback**: Ability to roll back canonical state to earlier milestone checkpoints when recovery fails.
