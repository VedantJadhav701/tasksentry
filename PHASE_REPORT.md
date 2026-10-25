# Phase 3 Report

## Status
PASS

## Implemented
Every required module and feature for Phase 3 has been implemented cleanly, robustly, and deterministically:

- `src/tasksentry/core/events.py`:
  - Extended `EventType` with Phase 3 lifecycle and control events: `REPLAN`, `COMPRESS`, `CHECKPOINT`, `ESCALATE`, `STOP`, `LOOP_DETECTED`, `DUPLICATE_BLOCKED`, `VERIFICATION_FAILED`, `VERIFICATION_PASSED`.
  - Added factory methods on `Event` for structured telemetry emission.
- `src/tasksentry/core/receipt.py`:
  - Extended `TaskReceipt` capturing end-to-end task accounting: `status`, `success`, `tokens`, `cost_usd`, `llm_calls`, `loop_warnings`, `verification_results`, `waste_report`, `final_answer`, `slo_met`, alongside Phase 2 budget and governor metrics.
- `src/tasksentry/harness/verification.py`:
  - `VerificationResult` and `VerificationGate` evaluating deterministic verifiers for success criteria and milestones.
  - Implemented all 9 required deterministic verifiers:
    1. `command_exit_code`: subprocess execution with timeout and return code assertion.
    2. `pytest`: subprocess isolated pytest runner checking exit code 0.
    3. `json_schema`: JSON structure and required keys validation on file or inline data.
    4. `file_exists`: checks target file existence.
    5. `git_diff_nonempty`: checks whether git working directory has unstaged or staged diffs.
    6. `regex_match`: pattern matching against file content or inline string.
    7. `numeric_range`: verifies numerical boundaries (`min`, `max`, `target`, `tolerance`).
    8. `python_assert`: subprocess-isolated Python script execution with timeout; never executes user modules in harness process.
    9. `artifact_exists`: checks presence of generated artifacts.
  - Strict completion rule: models cannot mark completion by themselves; all success criteria must pass via verification.
- `src/tasksentry/harness/stop_conditions.py`:
  - `evaluate_stop_conditions(...)` orchestrating canonical loop thresholds with runtime bounds:
    - Verifies success criteria completion.
    - Evaluates budget exhaustion (hard limit).
    - Checks 3-blocked-duplicate escalation.
    - Detects unsafe writes requiring human intervention.
    - Integrates Phase 1 canonical stop policy (`STOP_NOW`, `WARN`, `CONTINUE`) based on `WindowGain`, `EMA`, `HBT`, and repeating action fingerprints.
- `src/tasksentry/harness/recovery.py`:
  - `RecoveryAction` enum: `RETRY`, `REPLAN`, `COMPRESS`, `CHECKPOINT`, `ESCALATE`, `STOP`, `WARN_BUDGET`, `PROMPT_APPROVAL`, `REJECT_COMPLETION`.
  - `RecoveryDecision` container.
  - `compute_backoff(...)` calculating exponential backoff with random jitter.
  - `compact_context(...)` compressing observation history while strictly preserving task goal, milestones, canonical facts, and active plan.
  - `RecoveryEngine` implementing the recovery policy matrix:
    - Transient tool error -> Retry with exponential backoff and jitter.
    - Malformed tool arguments -> Return corrective schema error.
    - Same tool fails 3 times -> Force replan.
    - No progress for 3 consecutive steps -> Force replan.
    - Context near limit -> Context compression and checkpointing.
    - Budget 80% consumed -> Budget warning.
    - Budget exhausted -> Stop with partial receipt.
    - Unsafe write -> Pause for approval.
    - Verification failed after completion claim -> Reject completion and continue or escalate.
    - 3 blocked duplicates -> Escalate.
- `src/tasksentry/harness/planner.py`:
  - `Plan` data structure tracking goal, milestones, active milestone, completed milestones, and next action.
  - `Planner` scheduling milestones and computing milestone progress.
  - Milestone progress rule: milestones become complete only when their configured verifier passes.
  - Dynamic replan rule: replanning preserves already completed milestones and strictly forbids deleting contract success criteria.
- `src/tasksentry/harness/action_gate.py`:
  - `ActionGate` regulating actions before execution:
    - Handles `complete_task` claims by invoking `VerificationGate` across all contract success criteria. If any criterion fails, completion is rejected and `VERIFICATION_FAILED` is recorded.
    - Passes tool invocations through `ToolGovernor` for schema validation, risk classification, write safety, and duplicate action fingerprinting.
- `src/tasksentry/harness/executor.py`:
  - `StepResult` capturing status (`success`, `error`, `timeout`, `blocked`), observation, APG score, state hashes, cost, tokens, and latency.
  - `Executor` orchestrating sandboxed tool calls, updating `CanonicalState`, computing `APG`, updating `WindowGain` and `EMA`, and recording resource usage.
- `src/tasksentry/harness/agent.py`:
  - `@runtime_checkable` `Agent` Protocol requiring `step(state, plan, history) -> dict[str, Any]`.
  - `ScriptedAgent` executing deterministic sequences of tool calls or actions.
  - `FakeCodingAgent` generating multi-step plans, editing code, running tests, and requesting verification.
- `src/tasksentry/core/runtime.py`:
  - `CASERuntime` implementing the 10-step CASE runtime loop:
    1. Read current canonical state.
    2. Ask the model for the next action.
    3. Validate and govern the action via `ActionGate`.
    4. Execute through the sandbox via `Executor`.
    5. Record observation, cost, latency, tokens, and events.
    6. Run verification checks for active milestones.
    7. Compute `APG` and state transitions.
    8. Update `WindowGain` and `EMA`.
    9. Apply stop and recovery policies via `evaluate_stop_conditions` and `RecoveryEngine`.
    10. Continue, replan, compress, stop, or escalate.
- `src/tasksentry/core/task.py`:
  - `AgentTask` binding contract, runtime, and agents (`task.run(agent=...)`), generating a comprehensive `TaskReceipt`.
- Test Suites:
  - `tests/test_verification.py`: 10 tests
  - `tests/test_recovery.py`: 6 tests
  - `tests/test_stop_conditions.py`: 6 tests
  - `tests/test_planner.py`: 5 tests
  - `tests/test_executor.py`: 4 tests
  - `tests/test_action_gate.py`: 4 tests
  - `tests/test_agent_runtime.py`: 5 tests
  - `tests/test_task_runtime.py`: 5 tests
  - Total: 45 new tests, 170 total passing tests across the entire repository.

## Mathematical behavior

### CASE Runtime Loop & State Transition
At step $t$, the system maintains canonical task state $s_t = (g, M_t, K_t, W_t)$.
The runtime asks the agent for action $a_t$.
`ActionGate` verifies that $a_t$ is valid, safe, and not a duplicate according to action fingerprint $\text{fp}_t$.
Upon execution, `Executor` evaluates transition $s_t \to s_{t+1}$ and records step metrics.

### Verification-Gated Completion
The agent cannot mark milestones or tasks complete by declaring intent.
Completion of milestone $m$ requires:
$$V_m(s_{t+1}) = \text{True}$$
Similarly, task completion requires:
$$\forall c \in \text{success\_criteria}, \quad V_c(s_{t+1}) = \text{True}$$
If an agent submits `complete_task` while any criterion fails, the gate rejects completion, records a `VERIFICATION_FAILED` event, and continues or escalates according to recovery policy.

### APG & WindowGain Accounting
Agent Progress Gain ($APG_t$) scores executed step $t$:
$$APG_t = \alpha_1 \cdot \text{StateChange}_t + \alpha_2 \cdot \text{MilestoneProgress}_t + \alpha_3 \cdot \text{InfoGain}_t + \alpha_4 \cdot \text{EvidenceNovelty}_t - \alpha_5 \cdot \text{RepetitionPenalty}_t - \alpha_6 \cdot \text{NormalizedCost}_t$$
$APG_t$ updates the rolling window of size $n$:
$$\text{WindowGain}_t = \sum_{i=t-n+1}^{t} APG_i$$
and the exponential moving average:
$$\text{EMA}_t = \beta \cdot \text{EMA}_{t-1} + (1 - \beta) \cdot APG_t$$

### Recovery Engine Decision Matrix
| Failure | Action | Trigger Condition |
|---|---|---|
| Transient tool error | Retry with exponential backoff & jitter | `is_transient == True`, attempt $\le 3$ |
| Malformed tool arguments | Return corrective schema error | Pydantic validation error |
| Same tool fails 3 times | Force replan | `consecutive_failures >= 3` |
| No progress for 3 steps | Force replan | `steps_without_progress >= 3` |
| Context near limit | Compress context and checkpoint | tokens $\ge 0.85 \times \text{limit}$ |
| Budget 80% consumed | Warn | usage $\ge 0.80 \times \text{limit}$ |
| Budget exhausted | Stop and produce partial receipt | usage $\ge 1.0 \times \text{limit}$ (hard limit) |
| Unsafe write | Pause for approval | write action violates safety policy |
| Verification fails after completion claim | Reject completion & continue/escalate | $\exists c: V_c == \text{False}$ on `complete_task` |
| 3 blocked duplicates | Escalate | `blocked_duplicates >= 3` |

### Backoff with Jitter
For retry attempt $k \ge 1$:
$$T_{\text{backoff}} = T_{\text{base}} \cdot 2^{k-1} + \text{Uniform}(0, \text{jitter})$$

## Test results
Actual output of running `conda run -n thermo_agent pytest -q`:
```
........................................................................ [ 42%]
........................................................................ [ 84%]
..........................                                               [100%]
170 passed in 7.66s
```

## Lint and type results
Actual output of running `conda run -n thermo_agent ruff check .`:
```
All checks passed!
```

Actual output of running `conda run -n thermo_agent mypy src/tasksentry`:
```
Success: no issues found in 33 source files
```

## Known limitations
- **Subprocess execution environment**: Verifiers such as `pytest`, `command_exit_code`, and `python_assert` invoke subprocesses. In environments where the Python executable path contains spaces or platform-specific characters (such as Windows default installations), arguments must be passed as lists rather than shell-joined strings to prevent delimiter misinterpretation.
- **Deterministic vs semantic verifiers**: Current verifiers execute deterministic checks (exit codes, regexes, schemas, numerical thresholds, file presence). Complex semantic code reviews or model self-judgments require wrapping within deterministic assertion scripts.

## Next phase
Phase 4: Benchmarks, CLI, and dashboard/telemetry.
