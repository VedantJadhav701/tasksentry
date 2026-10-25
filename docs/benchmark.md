# TaskSentryBench v0.1 Specification

TaskSentryBench v0.1 is an offline-first, deterministic, fair, and reproducible benchmarking system designed to measure autonomous agent harness efficiency, loop escape capabilities, verification accuracy, and budget governance.

## Benchmark Tracks

### 1. Offline Regression Track (`offline-v0.1`)
- **Execution**: 100% offline, deterministic, and fast.
- **Agent Simulation**: Uses scripted mock agents with injected failure scenarios and traps.
- **Coverage**: 26 tasks spanning 10 representative failure and workflow families.
- **Purpose**: CI/CD regression verification, mathematical invariant validation, and harness logic testing without model latency or API costs.

### 2. Local Real-Model Track (`ollama-v0.1`)
- **Execution**: Local inference against Ollama running open-weights models (`llama3.2:1b`, `qwen3:4b-instruct-2507-q4_K_M`, etc.).
- **Purpose**: Empirical evaluation of real LLM decision-making, prompt reflection, and harness intervention under live token generation.

## Evaluated Task Families (26 Tasks)

1. **Code Repair**: Syntax error resolution, type mismatch resolution, boundary condition fixes.
2. **Repository Analysis**: Dead code detection, code churn analysis, dependency graph extraction.
3. **RAG-Style Research**: Keyword lookup, entity extraction, multi-document summarization.
4. **Multi-Step API Workflows**: Auth token retrieval, paginated data fetch, idempotent write-and-verify.
5. **Transient Tool Failures**: Injected HTTP 503 errors, lock timeouts, socket reset retries.
6. **Duplicate-Call Traps**: Stagnant search loops, status polling loops, repeated identical read loops.
7. **Context-Bloat Traps**: Repetitive verbose logs, massive multi-megabyte tool payloads.
8. **Premature-Completion Traps**: Early completion claim without verification, skipped milestone verification.
9. **Budget-Constrained Planning**: Strict token limits, strict USD cost caps.
10. **Recovery from Failure**: Invalid JSON argument recovery, persistent tool failure replanning.

## Compared Systems & Ablations

1. **Baseline ReAct scaffold**: Minimal unconstrained loop without verification gate or recovery.
2. **Baseline + safeguards**: ReAct loop augmented with maximum step caps and exact duplicate call suppression.
3. **Baseline + naive reflection**: ReAct with post-failure self-reflection prompts, but without objective verification.
4. **TaskSentry CASE harness**: Full harness featuring Agent Progress Gain (APG) loop control, ActionGate verification, RecoveryEngine, and ToolGovernor.
5. **CASE ablation (no APG)**: TaskSentry CASE with APG anti-loop detection disabled.
6. **CASE ablation (no verification)**: TaskSentry CASE allowing model completion claims without verifier checks.

## Standard Metrics & Formulas

- **Task Success Rate**: `successful_tasks / total_tasks`
- **pass@k**: Binomial estimator for success within `k` independent attempts.
- **Cost / Tokens per Successful Task**: Total cost/tokens spent divided by number of successfully verified tasks.
- **Tool Calls per Task**: Mean tool executions per task.
- **Duplicate Tool Calls**: Number of identical action calls attempted.
- **Wasted Action Rate**: Fraction of tool actions resulting in non-positive APG.
- **Loop Escape Rate**: Fraction of tasks encountering low-gain warnings that successfully recovered.
- **p50 / p95 Latency**: Wall-clock execution time percentiles.
- **Budget Compliance Rate**: Percentage of runs that stayed strictly within token, cost, and tool call caps.
- **Verification Pass Rate**: Ratio of passed verifications to total verification checks.
- **Efficiency-Adjusted Success Rate**: `success_rate * (1.0 - wasted_action_rate)`

## Running the Benchmark

CLI:
```bash
# Run offline regression suite
tasksentry benchmark --suite offline-v0.1 --output reports/offline-benchmark.json

# Run local Ollama suite
tasksentry benchmark --suite ollama-v0.1 --routine-model llama3.2:1b
```

Python SDK:
```python
from tasksentry.benchmark import run_benchmark_suite

data = run_benchmark_suite(
    suite_name="offline-v0.1",
    seed=42,
    output_path="reports/offline-benchmark.json",
)
```
