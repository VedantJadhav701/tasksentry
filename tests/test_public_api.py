"""Unit tests for the public SDK surface and requested example workflow."""

import os
import sys

from tasksentry import (
    AgentTask,
    Budget,
    BudgetPolicy,
    TaskReceipt,
    ToolGovernor,
    ToolRegistry,
    budget,
    tool,
)


def test_public_imports() -> None:
    assert AgentTask is not None
    assert Budget is not None
    assert BudgetPolicy is not None
    assert TaskReceipt is not None
    assert ToolGovernor is not None
    assert ToolRegistry is not None
    assert budget is not None
    assert tool is not None


def test_tool_decorator_registration() -> None:
    @tool(name="sample_read", description="Sample tool for reading", risk="read")
    def sample_read(path: str) -> str:
        return f"content of {path}"

    assert sample_read.name == "sample_read"
    assert sample_read.risk == "read"
    assert sample_read.callable(path="test.txt") == "content of test.txt"


def test_agent_task_kwarg_construction() -> None:
    task = AgentTask(
        goal="Find duplicated pricing logic and make the tests pass.",
        max_llm_calls=12,
        max_tool_calls=15,
        max_tokens=60_000,
        max_cost_usd=0.50,
        max_wall_time_seconds=300,
        success_criteria=[
            {
                "id": "tests_pass",
                "verifier": "numeric_range",
                "config": {"value": 1, "min": 0},
            }
        ],
        milestones=[
            {
                "id": "identify_duplicated_logic",
                "done_when": {
                    "verifier": "numeric_range",
                    "config": {"value": 1, "min": 0},
                },
            }
        ],
    )

    assert task.contract.goal == "Find duplicated pricing logic and make the tests pass."
    assert task.contract.budget.max_llm_calls == 12
    assert task.contract.budget.max_cost_usd == 0.50
    assert len(task.contract.success_criteria) == 1
    assert len(task.contract.milestones) == 1

    result = task.run(agent="fake-coding-agent")
    assert result.receipt is not None
    assert result.receipt.task_id == task.contract.task_id
    assert result.status in ("completed", "stopped")


def test_public_api_example_execution(tmp_path: os.PathLike[str]) -> None:
    # Set up artifact file for milestone
    art_dir = os.path.join(str(tmp_path), "analysis")
    os.makedirs(art_dir, exist_ok=True)
    art_file = os.path.join(art_dir, "duplicate_report.json")
    with open(art_file, "w", encoding="utf-8") as f:
        f.write('{"duplicates": []}')

    task = AgentTask(
        goal="Find duplicated pricing logic and make the tests pass.",
        max_llm_calls=12,
        max_tool_calls=15,
        max_tokens=60_000,
        max_cost_usd=0.50,
        max_wall_time_seconds=300,
        success_criteria=[
            {
                "id": "tests_pass",
                "verifier": "command_exit_code",
                "config": {"command": [sys.executable, "-c", "import sys; sys.exit(0)"]},
            }
        ],
        milestones=[
            {
                "id": "identify_duplicated_logic",
                "done_when": {
                    "verifier": "artifact_exists",
                    "config": {"artifact": art_file},
                },
            }
        ],
    )

    result = task.run(agent="fake-coding-agent")
    assert result.receipt is not None
    assert result.success is True
    assert result.receipt.status == "completed"
