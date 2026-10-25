# TaskSentry Console

The **TaskSentry Console** is a chat-first local agent control plane and telemetry dashboard. It transforms TaskSentry from a developer CLI tool into an interactive local agent console with real-time semantic model routing across your local Ollama LLMs.

---

## Key Features

1. **Chat-First Workflow**:
   - Submit natural language tasks directly in an interactive chat interface.
   - Automatically translates user requests into governed [`TaskContract`](file:///C:/Users/HP/projects/Tasksentry/src/tasksentry/core/contract.py) specifications with objective verification gates and budget limits.

2. **Live Execution & Streaming**:
   - Streams reasoning steps, planner milestones, assistant messages, and tool invocations via Server-Sent Events (SSE).
   - Real-time token generation telemetry and step timings.

3. **Semantic Routing Inspector**:
   - Directs queries between **Fast Routine Models** (e.g., `qwen2.5:3b`, `llama3.2:1b`, `gemma2:2b`) and **Deep Reasoning Models** (e.g., `qwen3:4b-instruct-2507-q4_K_M`, `ornith:latest`, `beam:cloud`).
   - Displays real-time routing explanations, signals (complexity, failure history, stagnation), and automatic model fallbacks for every step.

4. **Human-in-the-Loop Approvals**:
   - Enforces approval gates for write-capable tools (e.g., `write_text_file`, `run_command`).
   - Execution pauses safely, emits `approval_required`, and prompts the user in chat to approve or reject the action.

5. **Budget Burn-Down & Loop Control**:
   - Live visual burn-down meters for token consumption, tool-call count, wall-clock time, and cost.
   - Real-time display of loop control metrics, WindowGain, and blocked duplicate actions.

6. **Router Playground**:
   - Interactive prompt comparison lab.
   - Test any prompt across routine, reasoning, and routed lanes side-by-side with latency, token counts, and routing rationales.

7. **Ollama Model Health**:
   - Real-time health, latency, context window allocations, and availability monitoring for local Ollama instances.

8. **Auditable Task Receipts**:
   - Instant visual summary and one-click JSON receipt download for audit trails.

---

## Quickstart

### Launching the Console

To start the local console server:

```powershell
python -m tasksentry.cli console --host 127.0.0.1 --port 8321
```

Then open your browser to:
[http://127.0.0.1:8321](http://127.0.0.1:8321)

---

## Architecture

```
                 TaskSentry Console UI
       (Chat, Live Run, Routing Inspector, Playground)
                         │
                 WebSocket / SSE
                         │
                  TaskSentry API
       (/api/chat/tasks, /stream, /approve, /receipt)
                         │
                         ▼
               Semantic Model Router
           (Signals, Lane Decision, Fallbacks)
              /                      \
      Routine Lane                Reasoning Lane
     (e.g., qwen2.5:3b)         (e.g., qwen3:4b)
              \                      /
               ▼                    ▼
             Local Ollama LLM Mesh (127.0.0.1:11434)
```

---

## Security & Local Privacy

- **Local-Only Binding**: Defaults strictly to `127.0.0.1`, keeping all prompt data and telemetry on your machine.
- **Strict Human Approval Gate**: Potentially destructive filesystem and shell actions require explicit user confirmation unless `--allow-writes` is enabled.
- **Budget Enforcer**: Hard limits immediately stop or escalate runs exceeding allotted token, tool-call, or wall-time thresholds.
