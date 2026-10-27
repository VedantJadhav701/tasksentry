# TaskSentry Security Architecture & Best Practices

Running autonomous agents with tool-calling capabilities presents unique operational and security risks, including prompt injection, unintentional state corruption, runaway API billing, and resource exhaustion.

TaskSentry provides a defense-in-depth control plane to mitigate these risks.

---

## 1. Sandbox Modes & Boundaries

### In-Process Mode (`mode="in_process"`)
- **Behavior**: Executes tool functions directly in the host Python process.
- **Security Boundary**: **None**. Runs with the exact permissions, environment variables, and memory access of the running application.
- **Use Case**: Offline testing, unit tests, and safe local development with known, trusted tools.

### Process-Isolated Mode (`mode="process_isolated"`)
- **Behavior**: Spawns independent child processes using Python's `multiprocessing` spawn context.
- **Security Boundary**: Protects the parent control plane against catastrophic interpreter crashes, memory leaks, unhandled signals, and runaway loops via wall-clock timeouts.
- **Limitations**: Child processes still run under the host operating system user account and have normal file system and network access.
- **Production Recommendation**: For running untrusted model-generated code in production, wrap tool execution in containerized environments (Docker, Podman, gVisor, or Firecracker microVMs).

---

## 2. Tool Risk Governance & Approval Gates

Every tool registered in `ToolRegistry` must declare a risk category:
- `read` (Risk 0.1): Read-only operations (e.g., `read_file`, `query_status`).
- `network` (Risk 0.4): External HTTP requests or remote API queries.
- `write` (Risk 0.5): File system writes or state modifications (e.g., `write_file`).
- `destructive` (Risk 1.0): File deletion, process termination, or database drops.

### Write Approval Callback
When `require_approval_for_writes = True` is set on the task safety rules, the harness halts execution of `write` and `destructive` tools until an explicit authorization callback returns `True`:

```python
from tasksentry.core.contract import SafetyRules

safety = SafetyRules(
    max_risk=0.5,
    require_approval_for_writes=True,
    allowed_tools=("read_file", "search_repo", "write_file"),
)
```

---

## 3. Domain data, tenancy, and command safety

Domain records are untrusted input. Ticket text, logs, retrieved SOP text, and
command output cannot change a command's catalog risk, tenant scope, autonomy
level, kill switch, or approval requirement. Domain actions are catalog IDs
with typed arguments and are rendered as argv lists; free-form model shell
commands are not an execution interface.

Each domain record carries a tenant ID. Redaction occurs before exported
training data and before an explicitly authorized cloud-model call. Cloud
recognition is off by default and requires a per-tenant opt-in. The reversible
redaction map must remain inside that tenant's protected boundary.

The autonomy ladder is fail-closed: L0 proposes only, L1 runs reads, L2 may
run reversible writes with verification/rollback evidence, and L3 always
requires approval. Unknown commands, failed policy evaluation, failed
verification, budget failures, kill-switch activation, rate-limit exhaustion,
and blast-radius violations do not execute.

The Console's harness review endpoints record approved/rejected proposals but
do not execute them. Use the existing approval manager for pending L3 actions.

---

## 4. Audit-chain scope

TaskSentry receipts and domain reports provide **integrity evidence** through
hashes and deterministic source hashes. This is not external notarization: an
operator who controls the storage can still delete or replace the whole local
history. Customer-held signing keys or an external timestamp/anchoring service
are required for independently anchored audit history and are not included in
the offline domain layer.

---

## 5. Budget Hard Limits

TaskSentry enforces hard budget limits prospectively:
- **Token Limits**: Prevents context-stuffing and excessive token consumption.
- **USD Cost Limits**: Prevents unexpected cloud model billing surges.
- **Tool Call Limits**: Caps total tool executions per task.
- **Wall-Time Limits**: Prevents infinite loops and hanging socket connections.

When a hard limit is breached, the harness emits a `BUDGET_HARD_LIMIT` event, sets the receipt status to `stopped`, and immediately halts execution.

---

## 6. Repetition & Duplicate Action Suppression

Prompt injection attacks or model confusion often cause agents to enter infinite repetition loops (e.g., polling an unchanged endpoint or repeatedly writing the same file).

TaskSentry computes action fingerprints that incorporate canonical state:
$$\text{fp} = \text{SHA256}(\text{tool\_name} \,\|\, \text{args} \,\|\, \text{hash}(s_t))$$

If an identical action is repeated beyond the configured threshold (`block_threshold = 2`), `ActionGate` rejects the call pre-execution without charging the tool budget. After 3 blocked duplicate attempts, the task is automatically escalated to a human operator.

---

## 7. Dashboard Security

The local developer dashboard binds to `127.0.0.1` by default:
- Do not expose port `8321` to public network interfaces.
- If remote dashboard access is required, place it behind an authenticating reverse proxy (such as Nginx or Caddy with OAuth/OIDC or mutual TLS).
