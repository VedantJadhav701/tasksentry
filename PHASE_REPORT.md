# Phase 2 Report

## Status
PASS

## Implemented
Every required module and feature for Phase 2 has been implemented cleanly and deterministically:

- `src/tasksentry/py.typed`: PEP 561 marker indicating typing support.
- `src/tasksentry/exceptions.py`:
  - `BudgetError`, `BudgetExceededError`
  - `PricingError`, `UnknownModelPriceError`
  - `ToolError`, `ToolRegistrationError`, `ToolValidationError`, `IsolationError`, `GovernorError`
- `src/tasksentry/core/events.py`:
  - `EventType` StrEnum and event definitions: `TOOL_REGISTERED`, `TOOL_VALIDATION_FAILED`, `TOOL_BLOCKED_DUPLICATE`, `TOOL_TIMEOUT`, `TOOL_ERROR`, `TOOL_SUCCESS`, `BUDGET_WARNING`, `BUDGET_EXCEEDED`, `BUDGET_HARD_LIMIT`, `RETRY`, `RETRY_EXEMPTED`
  - `Event` model capturing lifecycle telemetry, metadata, and timestamps
- `src/tasksentry/core/receipt.py`:
  - `TaskReceipt` capturing post-run accounting: budget usage, pricing model, tool calls, duplicate calls blocked, retries, retry exemptions, risk events, warnings, errors, controller penalty, and final status
- `src/tasksentry/budget/pricing.py`:
  - `ModelPricing`, `CostEstimate`, `PricingTable`
  - `calculate_cost(...)` using `Decimal` math with 6+ decimal places precision
  - Fallback pricing and custom model pricing overrides
  - Non-negative token validation and currency retention
- `src/tasksentry/budget/meter.py`:
  - `UsageMeter` mutable resource accumulator for tokens, cost, calls, and latency
- `src/tasksentry/budget/policy.py`:
  - `BudgetPolicy` defining hard vs. soft limits and warning ratios (default 80%)
- `src/tasksentry/budget/budget.py`:
  - Pydantic v2 `Budget` tracker
  - Multi-dimensional tracking: `input_tokens`, `output_tokens`, `total_tokens`, `cost_usd`, `llm_calls`, `tool_calls`, `retries`, `wall_time_seconds`
  - 80% limit warning (`BUDGET_WARNING`) and 100% threshold emission (`BUDGET_EXCEEDED`)
  - Hard limit enforcement via `BudgetExceededError` and prospective check `can_afford(...)`
  - Immediate usage recording before raising errors on overshoot
- `src/tasksentry/tools/schema.py`:
  - Dynamic Pydantic v2 input model construction via `build_input_model_from_callable`
  - Standard JSON Schema extraction via `generate_json_schema`
  - Argument validation and structured error generation via `validate_tool_arguments`
- `src/tasksentry/tools/registry.py`:
  - `Tool` model and `ToolRegistry`
  - `@tool` decorator supporting type annotations, risk classes, idempotency, and timeouts
  - Duplicate registration detection and allowlist verification
- `src/tasksentry/tools/sandbox.py`:
  - Two execution modes:
    - `"in_process"`: Deterministic testing mode with output capture, explicitly documented as NOT a security sandbox
    - `"process"`: Process-isolated execution using `ProcessPoolExecutor`, enforcing timeouts, capturing stdout/stderr, and checking serialization
  - Serialization guards raising `IsolationError` for lambdas, local closures, and unpicklable objects
- `src/tasksentry/tools/governor.py`:
  - `ToolGovernor` implementing the complete 9-point pre-execution gate:
    1. Tool existence
    2. Tool allowlist
    3. Schema argument validation
    4. Prospective budget affordability
    5. Risk classification
    6. Write safety approval policy
    7. Duplicate action fingerprint check
    8. Retry exemptions evaluation
    9. Timeout configuration
  - Exact action fingerprint matching with canonical state hash
  - Automatic blocked-duplicate penalty (-0.5) recording without polluting `WindowGain`
  - Escalation after 3 blocked duplicate actions
- `src/tasksentry/tools/builtin.py`:
  - Deterministic offline builtins: `echo`, `add`, `fail_always`, `fail_times`, `slow_tool`, `read_text_file`, `write_text_file`, `list_directory`, `run_command`, `json_validate`
- Test Suites:
  - `tests/test_budget.py`: 11 tests
  - `tests/test_pricing.py`: 7 tests
  - `tests/test_tool_registry.py`: 5 tests
  - `tests/test_tool_schema.py`: 5 tests
  - `tests/test_sandbox.py`: 7 tests
  - `tests/test_tool_governor.py`: 10 tests
  - `tests/test_budget_integration.py`: 3 tests
  - Total: 48 new tests, 125 total passing tests.

## Mathematical behavior

### APG Integration
Agent Progress Gain ($APG_t$) scores executed agent actions:
$$APG_t = \alpha_1 \cdot \text{StateChange}_t + \alpha_2 \cdot \text{MilestoneProgress}_t + \alpha_3 \cdot \text{InfoGain}_t + \alpha_4 \cdot \text{EvidenceNovelty}_t - \alpha_5 \cdot \text{RepetitionPenalty}_t - \alpha_6 \cdot \text{NormalizedCost}_t$$
The governor coordinates directly with `ProgressTracker` to track executed actions and action fingerprints, ensuring executed actions update the rolling window while blocked calls are kept separate.

### Duplicate Fingerprint Rule
An action fingerprint is strictly deterministic:
$$\text{fingerprint}_t = \text{hash}(\text{tool\_name}, \text{canonical\_json}(\text{arguments}), \text{state\_hash\_at\_call})$$
Because the canonical state hash $s_t = (g, M_t, K_t, W_t)$ is incorporated into the fingerprint, actions executed across state transitions (e.g. running unit tests before editing code vs. running unit tests after editing code) yield distinct fingerprints and are never treated as duplicate repetitions.

A tool call is blocked before execution if and only if:
$$\text{fingerprint\_count} \ge 2 \quad \text{AND} \quad \text{no retry exemption applies}$$

### Retry Exemptions
A repeated action is exempt from the repetition penalty and duplicate blocking if any of the following objective conditions hold:
1. Previous attempt failed with a transient error.
2. Arguments changed meaningfully.
3. Durable canonical task state changed.
4. Previous observation was an error.
5. Retry produced novel evidence above threshold.
6. The tool is explicitly marked idempotent and safe by policy.

### Blocked Duplicate Penalty
When an action is blocked as a duplicate:
1. The tool callable is never invoked.
2. No successful action is recorded.
3. The call output is excluded from evidence-novelty calculations.
4. A distinct `TOOL_BLOCKED_DUPLICATE` event is recorded.
5. A separate, fixed controller penalty of $-0.5$ is added to `controller_penalty_total`.
6. Escalation is triggered only after 3 blocked duplicate actions occur within a single task run.

### Why Blocked Duplicates are Excluded from WindowGain
`WindowGain_t = \sum_{i=t-n+1}^{t} APG_i$ measures the actual rate of productive forward progress of executed steps. Incorporating blocked duplicate attempts into `WindowGain` would corrupt the signal by diluting recent executed action scores and could artificially mask progress or trigger premature stop verdicts on otherwise healthy step sequences. Instead, the governor imposes an immediate external controller penalty ($-0.5$) tracked in `TaskReceipt` and escalates directly after 3 blocked calls.

## Test results
Actual output of running `conda run -n thermo_agent pytest -q`:
```
........................................................................ [ 57%]
.....................................................                    [100%]
125 passed in 4.50s
```

## Lint and type results
Actual output of running `conda run -n thermo_agent ruff check .`:
```
All checks passed!
```

Actual output of running `conda run -n thermo_agent mypy src/tasksentry`:
```
Success: no issues found in 23 source files
```

## Known limitations
- **In-process mode is not a security sandbox**: `in_process` mode executes callables directly within the host Python process. It is intended solely for deterministic testing and fast unit tests, providing no memory, syscall, or network isolation, and cannot forcibly terminate infinite loops or segmentation faults.
- **Pricing tables may become outdated**: Token costs across AI providers change periodically. Builtin pricing values serve as reference defaults; production environments should specify up-to-date pricing tables or explicit per-model overrides.
- **Process isolation requires picklable tools**: In `process` mode, functions, arguments, and return values are serialized via `pickle`. Dynamic closures, local lambdas, and non-picklable OS handles cannot be executed in process mode and will raise `IsolationError`.
- **Windows spawn behavior**: On Windows, Python's multiprocessing exclusively utilizes the `spawn` start method rather than `fork`. All isolated tool functions must reside at module scope and be importable by child worker processes.

## Next phase
Phase 3: Verification, recovery, and harness loop.
