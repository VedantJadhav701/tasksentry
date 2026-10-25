# TaskSentry Quickstart Guide

Get up and running with TaskSentry in 5 minutes.

---

## 1. Installation

Install TaskSentry with development, dashboard, and Ollama support:

```bash
git clone https://github.com/VedantJadhav701/tasksentry.git
cd tasksentry
pip install -e ".[dev,dashboard,ollama]"
```

Verify your installation:
```bash
tasksentry --help
```

---

## 2. Run the Built-In Demo

Run the offline coding agent demo:

```bash
tasksentry demo
```

Expected output:
```
Running TaskSentry offline demo...
Task 'task-offline-demo' executed in 3 steps.
Status: completed
Success: True
Total tokens: 350
Total cost (USD): $0.000700
All verification gates passed!
Receipt stored in SQLite: tasksentry.db
```

---

## 3. Create Your First Governed Task

Use the `AgentTask` Python SDK to create a governed task with custom tools, verification criteria, and budget limits:

```python
from tasksentry import AgentTask, tool
from pydantic import BaseModel


# 1. Define governed tools
@tool(risk="read")
def check_service_status(service_name: str) -> str:
    """Check health status of a service."""
    return f"{service_name} is running normally."


@tool(risk="write")
def restart_service(service_name: str) -> str:
    """Restart a service (requires write approval if configured)."""
    return f"{service_name} successfully restarted."


# 2. Define a success criterion
criterion = {
    "id": "status_check",
    "verifier": "exact_match",
    "config": {"expected": "auth-service is running normally."},
}

# 3. Create and run the task with hard budget limits
task = AgentTask(
    goal="Ensure auth-service is operational",
    max_tool_calls=5,
    max_cost_usd=0.05,
    success_criteria=[criterion],
    tools=[check_service_status, restart_service],
)

receipt = task.run()
print("Task status:", receipt.status)
print("Success:", receipt.success)
print("Tool calls executed:", receipt.tool_calls)
print("Tokens consumed:", receipt.total_tokens)
```

---

## 4. Wrap an Existing Agent with `budget()`

TaskSentry can wrap any existing agent loop, LangGraph graph, or custom script with ambient budget tracking:

```python
from tasksentry import budget

with budget(max_tokens=2000, max_cost_usd=0.02) as b:
    # Ambient tracking automatically measures tokens, tool calls, and time
    b.record_usage(input_tokens=500, output_tokens=150, cost_usd=0.003)
    b.record_tool_call()
    
    # Check remaining budget
    remaining = b.remaining_budget()
    print("Remaining cost:", remaining.cost_usd)
    print("Remaining tokens:", remaining.tokens)

# Obtain receipt
print("Final receipt:", b.receipt())
```

---

## 5. View the Local Dashboard

Launch the developer dashboard to visually inspect task runs, receipts, events, and metrics:

```bash
tasksentry dashboard --port 8321
```

Open `http://127.0.0.1:8321` in your browser. The dashboard runs locally and displays real-time execution receipts, step-by-step event logs, and benchmark comparisons.
