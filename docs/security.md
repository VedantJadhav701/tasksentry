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

## 3. Budget Hard Limits

TaskSentry enforces hard budget limits prospectively:
- **Token Limits**: Prevents context-stuffing and excessive token consumption.
- **USD Cost Limits**: Prevents unexpected cloud model billing surges.
- **Tool Call Limits**: Caps total tool executions per task.
- **Wall-Time Limits**: Prevents infinite loops and hanging socket connections.

When a hard limit is breached, the harness emits a `BUDGET_HARD_LIMIT` event, sets the receipt status to `stopped`, and immediately halts execution.

---

## 4. Repetition & Duplicate Action Suppression

Prompt injection attacks or model confusion often cause agents to enter infinite repetition loops (e.g., polling an unchanged endpoint or repeatedly writing the same file).

TaskSentry computes action fingerprints that incorporate canonical state:
$$\text{fp} = \text{SHA256}(\text{tool\_name} \,\|\, \text{args} \,\|\, \text{hash}(s_t))$$

If an identical action is repeated beyond the configured threshold (`block_threshold = 2`), `ActionGate` rejects the call pre-execution without charging the tool budget. After 3 blocked duplicate attempts, the task is automatically escalated to a human operator.

---

## 5. Dashboard Security

The local developer dashboard binds to `127.0.0.1` by default:
- Do not expose port `8321` to public network interfaces.
- If remote dashboard access is required, place it behind an authenticating reverse proxy (such as Nginx or Caddy with OAuth/OIDC or mutual TLS).
