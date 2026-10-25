"""Example: Autonomous coding agent governed by TaskSentry.

Runs 100% offline using deterministic in-memory tools.

Expected output:
    Task 'coding-repair-demo' started.
    Executing steps with TaskSentry governance...
    Task finished with status: 'completed', success=True

Exit condition:
    Exits with code 0 on verified task completion.
"""

import sys
from typing import Any

from pydantic import BaseModel

from tasksentry import AgentTask
from tasksentry.tools.registry import Tool, ToolRegistry


class ReadInput(BaseModel):
    path: str


class WriteInput(BaseModel):
    path: str
    content: str


class TestInput(BaseModel):
    suite: str


# File mock storage
workspace = {"src/calc.py": "def add(a, b): return a - b  # BUG"}


def read_file(path: str) -> str:
    """Read source code."""
    return workspace.get(path, "")


def write_file(path: str, content: str) -> str:
    """Write corrected source code."""
    workspace[path] = content
    return f"Wrote {len(content)} bytes to {path}"


def run_tests(suite: str) -> dict[str, Any]:
    """Execute unit test suite."""
    if "return a + b" in workspace.get("src/calc.py", ""):
        return {"new_world": {"tests_passed": 10, "status": "PASSED"}, "result": "10 passed"}
    return {"new_world": {"tests_passed": 0, "status": "FAILED"}, "result": "1 failed"}


def main() -> int:
    print("Task 'coding-repair-demo' started.")

    reg = ToolRegistry()
    reg.register(Tool(name="read_file", input_model=ReadInput, callable=read_file, risk="read"))
    reg.register(Tool(name="write_file", input_model=WriteInput, callable=write_file, risk="write"))
    reg.register(Tool(name="run_tests", input_model=TestInput, callable=run_tests, risk="read"))

    # Objective success criterion: test suite must report at least 1 test passed
    criterion = {
        "id": "unit_tests_pass",
        "verifier": "numeric_range",
        "config": {"key": "tests_passed", "min": 1},
    }

    # Pre-scripted actions demonstrating realistic repair sequence
    actions = [
        {"type": "tool_call", "tool": "read_file", "arguments": {"path": "src/calc.py"}},
        {
            "type": "tool_call",
            "tool": "write_file",
            "arguments": {"path": "src/calc.py", "content": "def add(a, b): return a + b"},
        },
        {"type": "tool_call", "tool": "run_tests", "arguments": {"suite": "unit"}},
        {"type": "complete_task"},
    ]

    task = AgentTask(
        goal="Fix addition logic in src/calc.py so unit tests pass",
        registry=reg,
        success_criteria=[criterion],
        max_tool_calls=5,
        max_tokens=4000,
    )
    # Grant approval for write actions in this demo
    task.runtime.governor.write_approval_callback = lambda name, args: True

    receipt = task.run(actions)
    print(f"Task finished with status: {receipt.status!r}, success={receipt.success}")
    assert receipt.success is True, "Task was expected to succeed"
    return 0


if __name__ == "__main__":
    sys.exit(main())
