# TaskSentry Local Dashboard Guide

TaskSentry includes a lightweight, modern, single-page developer dashboard powered by FastAPI and vanilla JavaScript.

---

## 1. Local-Only Design & Security

- **Strict Local Binding**: The dashboard binds exclusively to `127.0.0.1:8321` by default.
- **Zero Cloud Telemetry**: Does not send usage metrics, telemetry, or task data to external servers.
- **No External Authentication**: Because it is designed solely for local developer inspection on loopback, it does not include user authentication. **Do not bind the dashboard to public interfaces or expose port 8321 to untrusted networks.**

---

## 2. Launching the Dashboard

CLI:
```bash
tasksentry dashboard --host 127.0.0.1 --port 8321
```

Python SDK:
```python
from tasksentry.dashboard import run_dashboard

run_dashboard(host="127.0.0.1", port=8321)
```

Visit `http://127.0.0.1:8321` in your web browser.

---

## 3. Dashboard Views & Features

1. **Tasks View**: Tabular overview of all executed tasks with status badges, elapsed wall-time, token usage, cost, and tool call counts.
2. **Task Detail View**: Deep inspection of an individual task, displaying:
   - Success criteria and milestone completion status.
   - Step-by-step action history and tool outputs.
   - Real-time event log (`TOOL_SUCCESS`, `BUDGET_EXCEEDED`, `LOOP_DETECTED`, etc.).
   - Interactive button to immediately stop a running task.
3. **Benchmarks View**: Displays aggregate benchmark performance across tested systems (`react_baseline`, `baseline_safeguards`, `baseline_reflection`, `tasksentry_case`).
4. **Model Comparison View**: Side-by-side performance comparison of routine and reasoning models across token consumption, latency, and loop escapes.
5. **CASE Ablations View**: Comparative view isolating the effect of APG loop control and verification gates.
6. **Ollama Health View**: Live status indicator of local Ollama server connectivity, active models, and response latency.

---

## 4. REST API Endpoints

The dashboard exposes standard JSON endpoints:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Dashboard health and service status. |
| `GET` | `/api/tasks` | Lists stored tasks with pagination (`?limit=50`). |
| `GET` | `/api/tasks/{task_id}` | Detailed task information and metadata. |
| `GET` | `/api/tasks/{task_id}/receipt` | Complete execution receipt for a task. |
| `GET` | `/api/tasks/{task_id}/events` | Chronological event stream for a task. |
| `GET` | `/api/metrics` | Aggregate metrics (success rate, average cost, total tokens). |
| `GET` | `/api/benchmarks` | Lists all recorded benchmark runs. |
| `GET` | `/api/benchmarks/{run_id}` | Detailed results of a specific benchmark run. |
| `GET` | `/api/ollama/models` | Probes local Ollama and returns available models. |
| `POST` | `/api/tasks/{task_id}/stop` | Marks an active task as stopped. |
