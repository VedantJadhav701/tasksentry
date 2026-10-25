# Phase 4 Report

## Status
PASS

## Implemented
Every required module and feature for Phase 4 has been implemented cleanly, deterministically, and with 100% test coverage:

- `src/tasksentry/__init__.py`:
  - Exposed complete public SDK interface: `AgentTask`, `Budget`, `BudgetPolicy`, `TaskReceipt`, `ToolGovernor`, `ToolRegistry`, `budget`, `tool`.
  - Exposed storage and registry classes: `AgentRegistry`, `ModelRegistry`, `InMemoryReceiptStore`, `SQLiteReceiptStore`, `ReceiptStore`.
- `src/tasksentry/config.py`:
  - Implemented `TaskSentryConfig` with configuration precedence: explicit kwargs > `TASKSENTRY_*` environment variables > `tasksentry.yaml` / `tasksentry.yml` > default fallbacks.
  - Never hardcodes or stores API keys.
- `src/tasksentry/exceptions.py`:
  - Added Phase 4 exceptions: `ModelError`, `ModelNotFoundError`, `StorageError`, `StorageTaskNotFoundError`, `AgentRegistryError`, `AgentNotFoundError`, `PolicyNotFoundError`.
- `src/tasksentry/core/task.py`:
  - Extended `AgentTask` to support high-level keyword configuration: `goal`, `max_llm_calls`, `max_tool_calls`, `max_tokens`, `max_cost_usd`, `max_wall_time_seconds`, `success_criteria`, `milestones`, `store`, and named agent string resolution via `AgentRegistry`.
- `src/tasksentry/core/receipt.py`:
  - Added `.receipt` convenience property on `TaskReceipt` returning self, enabling `print(result.receipt)` workflows.
- `src/tasksentry/budget/budget.py`:
  - Implemented `budget` context manager and `BudgetContext` powered by `contextvars.ContextVar`.
  - Added methods: `record_usage`, `record_tool_call`, `check`, `remaining_budget`, `receipt`.
  - Added enforcement modes: `raise` (`BudgetExceededError`), `summarize_and_stop`, user-provided `stop_callback`, and `both`.
- `src/tasksentry/models/`:
  - `base.py`: Defined `ModelResponse` data model and `ModelClient` protocol.
  - `fake_model.py`: Deterministic offline `FakeModel` supporting queued canned responses and fallback message generation.
  - `openai_compat.py`: `OpenAICompatibleClient` connecting to any OpenAI-compatible endpoint with tool schema conversion, token tracking, custom base URLs, and structured `ModelError` handling.
  - `registry.py`: Implemented `ModelRegistry` (with custom Python callable models) and `AgentRegistry` loading declarative specifications from `agents/agents.yaml` and `agents/policies.yaml`.
- `agents/` & `prompts/`:
  - `agents/agents.yaml`: Declared `fake-coding-agent` mapping to `fake-model`, tools (`read_file`, `run_tests`, `search_workspace`), prompt file, and policy reference.
  - `agents/policies.yaml`: Declared `coding-agent-default` execution policy.
  - `prompts/coding_agent.md`: System prompt for the coding agent.
- `src/tasksentry/integrations/`:
  - `openai.py`: Implemented `tracked_client` returning an OpenAI-compatible client wrapper that automatically tracks token consumption, calculates costs using `DEFAULT_PRICING_TABLE`, and updates the active ambient `BudgetContext`.
- `src/tasksentry/storage/`:
  - `receipts.py`: Defined `ReceiptStore` protocol.
  - `memory.py`: `InMemoryReceiptStore` for thread-safe in-memory caching and testing.
  - `sqlite.py`: `SQLiteReceiptStore` local database with idempotent schema initialization, indexed lookups on `task_id` and `status`, transactions, and parameterized SQL queries preventing SQL injection.
- `src/tasksentry/cli.py`:
  - Standard library CLI supporting subcommands: `demo`, `run --task <path>`, `tasks`, `task <id>`, `receipt <id>`.
  - `examples/coding_task.yaml`: Offline sample task contract.
- Test suites:
  - Added 42 new unit tests across 10 test modules (`test_public_api.py`, `test_agent_registry.py`, `test_budget_wrapper.py`, `test_openai_compat.py`, `test_openai_integration.py`, `test_storage_memory.py`, `test_storage_sqlite.py`, `test_receipt_store.py`, `test_config.py`, `test_cli.py`).
  - Total tests passing: 212 tests.

## Public API
The public SDK surface is exported directly from the top-level `tasksentry` namespace:

```python
from tasksentry import AgentTask, tool

@tool
def read_file(path: str) -> str:
    """Read a file."""
    return ""

@tool
def run_tests() -> dict:
    """Run tests."""
    return {"exit_code": 0}

task = AgentTask(
    goal="Find duplicated pricing logic and make the tests pass.",
    max_llm_calls=12,
    max_tool_calls=15,
    max_tokens=60_000,
    max_cost_usd=0.50,
    max_wall_time_seconds=300,
    success_criteria=[
        {
            "id": "tests_pass",
            "verifier": "pytest",
            "config": {"command": "pytest -q"},
        }
    ],
    milestones=[
        {
            "id": "identify_duplicated_logic",
            "done_when": {
                "verifier": "artifact_exists",
                "config": {"artifact": "analysis/duplicate_report.json"}
            }
        }
    ],
)

result = task.run(agent="fake-coding-agent")
print(result.receipt)
```

## Agent registry
The agent resolution workflow follows a declarative pipeline:
1. When `task.run(agent="fake-coding-agent")` is called, the runner checks `AgentRegistry`.
2. Agent specifications are read from `agents/agents.yaml` and policy definitions from `agents/policies.yaml`.
3. The registry checks:
   - That the agent identifier exists (raising `AgentNotFoundError` if missing).
   - That the associated model is registered in `ModelRegistry` (raising `ModelNotFoundError` if missing).
   - That the configured policy exists (raising `PolicyNotFoundError` if missing).
   - That all tools specified in the agent's tool list are available in `ToolRegistry` (raising `ToolError` if missing).
   - That the system prompt file exists and is readable (raising `AgentRegistryError` if missing).
4. Policy overrides are merged on top of base policies.
5. The agent is instantiated with resolved model, tools, prompt, and policy.

## Budget wrapper
The standalone budget context manager leverages Python's `contextvars.ContextVar`:
- `_current_budget_context: contextvars.ContextVar[BudgetContext | None]` stores the ambient budget context.
- Ambient contexts are isolated per execution context / thread / coroutine with zero process-global state leakage.
- Nested `with budget(...)` blocks correctly save and restore outer contexts via context tokens.
- Works independently of whether the user agent utilizes the full TaskSentry harness.

Enforcement modes supported:
1. `on_exceed="raise"`: Immediately raises `BudgetExceededError` when hard limits are crossed.
2. `on_exceed="summarize_and_stop"`: Marks the context as stopped (`ctx.stopped = True`), halts subsequent actions, and generates a partial `TaskReceipt` without raising an exception.
3. `stop_callback`: User-defined callable invoked upon limit violation.
4. `on_exceed="both"`: Calls the stop callback / records stoppage, and raises `BudgetExceededError`.

## Storage
Task receipts and execution contracts are managed via the `ReceiptStore` protocol:
- **`InMemoryReceiptStore`**: Fast, thread-safe in-memory store suitable for testing and ephemeral workflows.
- **`SQLiteReceiptStore`**: Local, self-contained file database using SQLite:
  - Idempotent table and index creation (`CREATE TABLE IF NOT EXISTS`).
  - Indexes on `task_id` and `status` for fast query performance.
  - Parameterized queries to eliminate SQL injection vulnerabilities.
  - ACID transactional integrity via Python `sqlite3` context management.
  - Stores receipt data, contract definitions, metadata, and timestamps (`created_at`, `updated_at`).

## CLI
The `tasksentry` CLI is implemented with standard library `argparse`:
- `python -m tasksentry.cli --help`: Displays help and subcommand information.
- `python -m tasksentry.cli demo`: Executes a fully offline autonomous agent task under budget control, outputs receipt metrics, and saves the record to SQLite.
- `python -m tasksentry.cli run --task <path>`: Parses a YAML task contract, executes it with the requested agent, and prints JSON receipt.
- `python -m tasksentry.cli tasks`: Lists recorded tasks from the SQLite database.
- `python -m tasksentry.cli task <task_id>`: Prints full record details for a specific task.
- `python -m tasksentry.cli receipt <task_id>`: Dumps the JSON receipt for a specific task.

## Test results
Actual output of running `conda run -n thermo_agent pytest -q`:
```
........................................................................ [ 33%]
........................................................................ [ 67%]
....................................................................     [100%]
212 passed in 8.25s
```

## Lint and type results
Actual output of running `conda run -n thermo_agent ruff check .`:
```
All checks passed!
```

Actual output of running `conda run -n thermo_agent mypy src/tasksentry`:
```
Success: no issues found in 46 source files
```

## Known limitations
- **OpenAI integration is optional**: The `tracked_client` wrapper is built to interface with OpenAI-compatible HTTP endpoints (such as vLLM, Ollama, or OpenAI) without requiring the external `openai` pip package. For native OpenAI client features (like function streaming), users can pass custom transports.
- **SQLite is local-only**: SQLite provides local single-host storage. Distributed or multi-node production deployments will require a dedicated database backend.
- **CLI is minimal**: The CLI focuses on core offline execution, contract running, and receipt inspection. It intentionally avoids heavy GUI/TUI framework dependencies.
- **No hosted dashboard yet**: Telemetry is currently inspected through the CLI and SQLite records. Phase 5 introduces the dashboard and benchmarking framework.

## Next phase
Phase 5: benchmark, reporting, and dashboard.
