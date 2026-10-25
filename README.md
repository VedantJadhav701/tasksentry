# TaskSentry

**TaskSentry is an open-source, budget-native agent harness and control plane for task-level cost, latency, reliability, and safety control.**

> **Agent frameworks help you build agents. TaskSentry helps you run them safely, affordably, and predictably in production.**

[![CI Status](https://img.shields.io/badge/CI-passing-brightgreen.svg)](https://github.com/VedantJadhav701/tasksentry/actions)
[![Python Versions](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![Type Checked](https://img.shields.io/badge/mypy-strict-blue.svg)](pyproject.toml)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

---

## Why TaskSentry Exists

Autonomous AI agents frequently fail in production due to three core operational issues:
1. **Runaway Billing**: Agents get stuck in repetitive polling or self-correction loops, consuming thousands of dollars in tokens without producing value.
2. **Premature Victory**: Models hallucinate or self-declare completion ("I have fixed the issue!") without passing objective tests or verifiable acceptance criteria.
3. **Execution Deadlocks**: Agents attempt the exact same failing tool action repeatedly, with no mathematical detection of stalled progress.

## What TaskSentry Solves

TaskSentry acts as an execution supervisor and control harness. It wraps agent execution in:
- **Prospective & Ambient Budgeting**: Hard caps on tokens, USD cost, wall-clock time, and tool invocations.
- **Verification Gates**: Objective verifiers (unit tests, numeric metrics, file assertions) that must pass before a task can be marked complete.
- **Agent Progress Gain (`APG`)**: A mathematical progress formulation detecting low-gain cycles, repetitive actions, and stalled execution.
- **Automated Tiered Recovery**: Graceful backoff retry, forced replanning, context compaction, and human escalation.
- **Immutable Task Receipts**: Cryptographically auditable receipts recording durable state changes, token consumption, and verifications.

## What TaskSentry Does NOT Do

- **TaskSentry does NOT replace LangGraph, CrewAI, AutoGen, or the OpenAI Agents SDK.** It is an execution harness and control layer that sits between your agent logic and host infrastructure.
- **TaskSentry does NOT provide an OS-level security boundary.** In-process mode runs with host privileges; process-isolated mode enforces timeouts and process boundaries, but untrusted multi-tenant code requires containerization (Docker, gVisor, microVMs).
- **TaskSentry does NOT claim to be the first budget-native harness, nor does it publish unverifiable benchmark superiority claims.**

---

## System Architecture

```
       +-------------------------------------------------------+
       |                     TaskContract                      |
       |  (Goal, Success Criteria, Milestones, Budget, Safety) |
       +-------------------------------------------------------+
                                  |
                                  v
+---------------------------------------------------------------------+
|                             CASERuntime                             |
|                                                                     |
|    +-------------+      +------------------+      +------------+    |
|    |   Planner   | ---> |    ActionGate    | ---> |  Executor  |    |
|    +-------------+      +------------------+      +------------+    |
|           ^                      |                       |          |
|           | (Replan)             | (Governed / Blocked)  v          |
|    +-------------+               v                 +-----------+    |
|    |  Recovery   | <----+------------------------+ |  Sandbox  |    |
|    |   Engine    |      |    ToolGovernor        | +-----------+    |
|    +-------------+      | (Pricing, Allowlist,   |       |          |
|                         |  Repetition Block)     |       v          |
|                         +------------------------+ +-----------+    |
|                                  |                 | Real Tool |    |
|                                  v                 +-----------+    |
|                         +------------------+                        |
|                         |  ProgressTracker |                        |
|                         | (APG, WindowGain)|                        |
|                         +------------------+                        |
+---------------------------------------------------------------------+
                                  |
                                  v
       +-------------------------------------------------------+
       |                      TaskReceipt                      |
       |   (Durable Facts, Events, Tokens, Cost, Verifications)|
       +-------------------------------------------------------+
```

---

## Core Concepts

1. **Task Contract (`TaskContract`)**: Declares the goal, budget limits, safety allowlists, intermediate milestones, and required verification criteria.
2. **Budget (`Budget` & `budget()`)**: Multi-dimensional meter tracking token consumption, estimated USD cost, wall-time, and tool invocations.
3. **Tool Governor (`ToolGovernor`)**: Enforces argument schema validation (Pydantic), tool allowlists, risk ratings, and repetition throttling.
4. **Verification Gate (`VerificationGate`)**: Evaluates objective criteria (unit tests, regex, numeric ranges) to block premature model completion claims.
5. **Information Gain (`HypothesisBeliefTracker`)**: Bayesian belief updating over hypothesis sets with entropy reduction scoring (or bounded proxy fallback).
6. **Loop Detection (`ProgressTracker`)**: Computes scalar Agent Progress Gain ($APG_t$) and rolling $WindowGain_t$ to detect and break execution deadlocks.
7. **Recovery Engine (`RecoveryEngine`)**: Tiered failure handling providing exponential backoff, forced replans, context compaction, and escalation.
8. **Task Receipt (`TaskReceipt`)**: Structured, immutable execution record detailing costs, duration, step events, and verification outcomes.

---

## Quickstart

### Installation

```bash
# Clone repository
git clone https://github.com/VedantJadhav701/tasksentry.git
cd tasksentry

# Install package with all extras
pip install -e ".[dev,dashboard,ollama,openai,benchmark]"
```

Verify baseline test suite:
```bash
python -m pytest -q
```

---

## Python SDK Examples

### 1. Creating a Governed Task (`AgentTask`)

```python
from pydantic import BaseModel
from tasksentry import AgentTask, tool
from tasksentry.tools.registry import Tool, ToolRegistry


class FileInput(BaseModel):
    path: str


class TestInput(BaseModel):
    suite: str


def read_source(path: str) -> str:
    return "def add(a, b): return a + b"


def run_unit_tests(suite: str) -> dict:
    return {"new_world": {"tests_passed": 12}, "status": "PASSED"}


# 1. Register tools
reg = ToolRegistry()
reg.register(Tool(name="read_source", input_model=FileInput, callable=read_source, risk="read"))
reg.register(
    Tool(name="run_unit_tests", input_model=TestInput, callable=run_unit_tests, risk="read")
)

# 2. Declare verifier-backed criterion
criterion = {
    "id": "tests_must_pass",
    "verifier": "numeric_range",
    "config": {"key": "tests_passed", "min": 1},
}

# 3. Create governed task
task = AgentTask(
    goal="Ensure addition logic passes unit tests",
    registry=reg,
    success_criteria=[criterion],
    max_tool_calls=5,
    max_tokens=2000,
)

# 4. Run task (using actions or an agent runner)
receipt = task.run(
    [
        {"type": "tool_call", "tool": "read_source", "arguments": {"path": "calc.py"}},
        {"type": "tool_call", "tool": "run_unit_tests", "arguments": {"suite": "unit"}},
        {"type": "complete_task"},
    ]
)

print(f"Task status: {receipt.status}, success: {receipt.success}, cost: ${receipt.cost_usd:.4f}")
```

### 2. Ambient Budget Tracking (`budget()`)

Wrap any existing agent framework (LangGraph, CrewAI, AutoGen) with zero intrusive code changes:

```python
from tasksentry import budget

with budget(max_tokens=4000, max_cost_usd=0.05, max_tool_calls=10) as b:
    # Your existing agent loop runs here
    b.record_usage(input_tokens=800, output_tokens=250, cost_usd=0.003)
    b.record_tool_call("web_search")

    # Check remaining budget anytime
    rem = b.remaining_budget()
    print(f"Remaining tokens: {rem['remaining_tokens']}")

# Fetch complete audit receipt
receipt = b.receipt()
print(f"Total tokens spent: {receipt.tokens}, status: {receipt.status}")
```

---

## CLI Usage

TaskSentry includes a full CLI (`tasksentry`):

```bash
# Run built-in offline demo
tasksentry demo

# Inspect executed tasks stored in SQLite
tasksentry tasks --limit 10

# Inspect a specific task receipt
tasksentry receipt task-offline-demo

# Check local Ollama daemon health
tasksentry ollama-health

# Launch the local dashboard
tasksentry dashboard --host 127.0.0.1 --port 8321
```

---

## TaskSentryBench v0.1

TaskSentryBench evaluates 6 systems across 26 tasks in 10 failure-mode families:
1. **`react_baseline`**: Minimal unconstrained loop without verification.
2. **`baseline_safeguards`**: ReAct loop + step caps + exact duplicate blocking.
3. **`baseline_reflection`**: ReAct with prompt reflection on failure.
4. **`tasksentry_case`**: Full CASE harness with APG loop control, verification gate, recovery engine, and budget governor.
5. **`case_ablation_no_apg`**: CASE harness with APG loop detection disabled.
6. **`case_ablation_no_verification`**: CASE harness allowing unverified completion claims.

### Running Benchmarks

```bash
# Run offline regression suite (fast, deterministic, zero API cost)
tasksentry benchmark --suite offline-v0.1 --output reports/offline-benchmark.json

# Run local Ollama benchmark suite (requires Ollama running locally)
tasksentry benchmark --suite ollama-v0.1 --routine-model llama3.2:1b
```

See [docs/benchmark.md](docs/benchmark.md) and [docs/ollama.md](docs/ollama.md) for full benchmark documentation.

---

## Local Dashboard

TaskSentry provides a local-only developer dashboard for inspecting tasks, receipts, step-by-step events, metrics, and benchmark reports:

```bash
tasksentry dashboard --host 127.0.0.1 --port 8321
```

Visit `http://127.0.0.1:8321` in your browser.
- **Strictly local**: Binds to `127.0.0.1` by default.
- **No telemetry**: Does not send analytics or external requests.
- **Inspection views**: Tasks, Task Detail with real-time logs, Benchmarks, Model Comparison, CASE Ablations, and Ollama Health.

---

## Honest Limitations

- **Offline Benchmark**: The offline regression suite (`offline-v0.1`) uses scripted agent actions to test mathematical invariants and control loop behavior under deterministic conditions. It does not measure open-ended reasoning capabilities of unconstrained LLMs.
- **Local Ollama Track**: Results depend on local GPU hardware and available VRAM. Running quantized models on CPU fallback will incur higher latencies.
- **Security Boundary**: In-process execution mode is not sandboxed. Process-isolated mode terminates hanging processes via timeouts, but does not isolate OS file system access. Use containerized execution for untrusted multi-tenant workloads.
- **Proxy Information Gain**: In tasks where an explicit hypothesis set is not provided, TaskSentry falls back to a bounded proxy metric based on milestone progress and open failures, which is not equivalent to full Bayesian mutual information.

---

## Documentation Index

- [Architecture Guide](docs/architecture.md)
- [Mathematical Foundations](docs/mathematics.md)
- [Quickstart Guide](docs/quickstart.md)
- [TaskSentryBench Specification](docs/benchmark.md)
- [Ollama Integration Guide](docs/ollama.md)
- [Configuration Reference](docs/configuration.md)
- [CLI Reference](docs/cli.md)
- [Local Dashboard Guide](docs/dashboard.md)
- [Security & Sandboxing](docs/security.md)
- [Project Roadmap](docs/roadmap.md)
- [Release Guide](docs/release.md)

---

## Project Roadmap

- **v0.1.0** (Current): Core CASE harness, APG loop detection, budget governor, TaskSentryBench v0.1, local dashboard.
- **v0.2.0**: Drop-in adapters for LangGraph, CrewAI, and OpenAI Agents SDK; Docker/container sandbox backend.
- **v0.3.0**: Live Ollama community leaderboard and PR regression benchmarking.
- **v0.4.0+**: Multi-tenant hosted dashboard, dynamic budget allocation, checkpoint rollbacks.

See [docs/roadmap.md](docs/roadmap.md) for details.

---

## Contributing

We welcome community contributions! Please review our [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md) before opening a pull request.

---

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
