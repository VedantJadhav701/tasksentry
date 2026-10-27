# TaskSentry System Architecture

TaskSentry is an open-source, budget-native agent harness and control plane for task-level cost, latency, reliability, and safety control.

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

## 1. Core Principles

1. **Separation of Harness and Model**: The harness owns task contracts, budget limits, verification gates, and tool governance. The model or agent proposes actions; the harness decides whether and how actions execute.
2. **Volatile-Free Canonical State**: Canonical task state $s_t = (g, M_t, K_t, W_t)$ tracks only durable facts and milestone completions. Ephemeral logging, wall-clock timestamps, and budget counters never pollute state hashes.
3. **Objective Verification Before Completion**: Completion is an objective claim that must pass all required verifiers (e.g., test suite pass, schema validation, file existence), not a prompt declaration.
4. **Budget as a First-Class Constraint**: Multi-dimensional budgets (tokens, cost USD, wall-time, tool calls) are enforced prospectively before tool execution and ambiently across LLM invocations.

---

## 2. Component Responsibilities

### `TaskContract` (`src/tasksentry/core/contract.py`)
Declares the task specification:
- `goal`: Natural language description of the objective.
- `success_criteria`: Verification criteria that must all pass for the task to be marked successful.
- `milestones`: Intermediate progress checkpoints that provide positive progress gain when achieved.
- `budget`: Hard limits on LLM calls, tool calls, tokens, USD cost, and wall-time.
- `safety`: Explicit tool allowlists, write approval requirements, and maximum allowed tool risk level.

### `CASERuntime` (`src/tasksentry/core/runtime.py`)
Orchestrates the iterative runtime loop:
- In each step:
  1. Requests proposed action from the agent.
  2. Submits proposed action to `ActionGate`.
  3. If action is a completion claim, evaluates verification gates; if all pass, concludes task. If verification fails, routes to `RecoveryEngine` and forces replan.
  4. If action is a tool call, evaluates tool schema, allowlists, and repetition blocking.
  5. Dispatches allowed actions through `Executor` and `Sandbox`.
  6. Evaluates mathematical stop conditions based on `WindowGain` and blocked duplicates.
  7. On completion or termination, produces an immutable `TaskReceipt`.

### `ActionGate` (`src/tasksentry/harness/action_gate.py`)
Pre-execution gatekeeper:
- Intercepts premature completion claims and tests them against `VerificationGate`.
- Checks prospective budget affordability.
- Computes canonical action fingerprints and enforces duplication thresholds.

### `ToolGovernor` (`src/tasksentry/tools/governor.py`)
Enforces runtime policy and charges meters:
- Validates argument schemas using Pydantic models.
- Checks risk ratings against task safety thresholds.
- Enforces write approval callbacks for destructive tools.
- Charges the budget meter only upon execution attempt (never for blocked actions).
- Applies controller penalties for blocked duplicates.

### `Sandbox` (`src/tasksentry/tools/sandbox.py`)
Provides isolation:
- `mode="in_process"`: Lightweight wrapper capturing stdout/stderr and handling exceptions.
- `mode="process_isolated"`: Spawns independent sub-processes using `multiprocessing` with wall-clock timeout enforcement.

### `ProgressTracker` (`src/tasksentry/math/progress.py`)
Computes Agent Progress Gain (`APG`), rolling `WindowGain`, and exponential moving averages (`EMA`). Employs exact fingerprint matching and semantic similarity to detect deadlocks.

### `RecoveryEngine` (`src/tasksentry/harness/recovery.py`)
Provides automated tiering for failures:
1. `CONTINUE` with exponential backoff on transient errors.
2. `FORCE_REPLAN` on disallowed actions or verification failures.
3. `COMPACT_CONTEXT` on repetitive steps or large context bloat.
4. `ESCALATE` after 3 consecutive blocked duplicates or exhausted recovery replans.

---

## 3. Data Flow

```
Agent Action -> ActionGate -> ToolGovernor -> Sandbox -> Tool Callable
                    |              |                         |
                    v              v                         v
              Verification    Budget Meter              Result/Error
                    |              |                         |
                    +--------------+-------------------------+
                                   |
                                   v
                            ProgressTracker
                         (APG & State Ledger)
                                   |
                                   v
                           Stop Conditions
```


---

## 4. Console & Semantic Routing Plane

The Phase 7 TaskSentry Console introduces a chat-first interactive plane with real-time semantic model routing across local Ollama LLMs:

```
           +---------------------------------------------+
           |             TaskSentry Console              |
           |  (Chat UI, SSE Stream, Routing Inspector)   |
           +---------------------------------------------+
                                  |
                                  v
           +---------------------------------------------+
           |             ConsoleRunManager               |
           |  (Async SSE Streams, Approvals, Run Queue)  |
           +---------------------------------------------+
                                  |
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
```

### Key Console Capabilities:
- **`SemanticModelRouter` (`src/tasksentry/models/router.py`)**: Dynamic signal-based routing classifying prompts into fast routine vs. deep reasoning lanes with automated fallbacks.
- **`ApprovalManager` (`src/tasksentry/console/approvals.py`)**: Human-in-the-loop pause-and-resume gate for unsafe write actions.
- **`RouterPlayground` (`src/tasksentry/console/routing.py`)**: Multi-lane comparison engine comparing routine, reasoning, and routed decisions.
- **`ConsoleRunManager` (`src/tasksentry/console/runs.py`)**: Background execution manager broadcasting lifecycle events via Server-Sent Events (SSE).

---

## 5. Domain DSLM and governed autonomy plane

The domain layer sits before and beside the existing CASE runtime:

```
Tickets / SOPs / outcomes
          |
          v
 Canonical schema -> redaction -> time/customer split
          |
          +--> typed command catalog (argv only, human-approved draft)
          |
          +--> SFT / preference / refusal datasets + dataset card
          |
          +--> shadow proposal -> autonomy policy -> ToolGovernor
                                      |
                                      v
                         simulated replay / real backend adapter
                                      |
                                      v
                         verification -> receipt / feedback
```

`tasksentry.domain.schema` is the single trajectory contract. `catalog.py`
keeps command identity, argument typing, risk, preconditions, verifier,
rollback, and tenant scope outside untrusted ticket/SOP text. `autonomy.py`
provides L0-L3 decisions, caps, kill switch, shadow records, and promotion
evidence. `replay.py` evaluates recorded observations through a deterministic
simulated backend before a model or catalog is promoted.

The Console exposes these controls through `/api/domain/autonomy`,
`/api/domain/reviews`, and `/api/domain/proposals`; review endpoints only
change review state and do not execute a command.
