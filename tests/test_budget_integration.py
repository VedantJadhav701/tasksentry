"""Integration tests: Budget + Governor + Sandbox."""

from pydantic import BaseModel

from tasksentry.budget.budget import Budget
from tasksentry.math.progress import ProgressConfig, ProgressTracker
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import Tool, ToolRegistry
from tasksentry.tools.sandbox import Sandbox


def test_budget_governor_sandbox_integration() -> None:
    registry = ToolRegistry()

    def multiply(a: int, b: int) -> int:
        return a * b

    registry.register(Tool(name="multiply", input_model=BaseModel, callable=multiply))
    budget = Budget(max_tool_calls=5)
    sandbox = Sandbox(mode="in_process")
    gov = ToolGovernor(registry, budget=budget, sandbox=sandbox)

    # Initial usage
    assert budget.tool_calls == 0

    res = gov.execute("multiply", {"a": 4, "b": 7})
    assert res["status"] == "success"
    assert res["result"] == 28

    # Tool call usage updated
    assert budget.tool_calls == 1
    assert budget.remaining_budget()["remaining_tool_calls"] == 4


def test_blocked_duplicate_does_not_consume_budget() -> None:
    registry = ToolRegistry()

    def perform_action(name: str) -> str:
        return f"done {name}"

    registry.register(
        Tool(name="action", input_model=BaseModel, callable=perform_action, idempotent=False)
    )

    budget = Budget(max_tool_calls=5)
    tracker = ProgressTracker(config=ProgressConfig(block_threshold=2))
    gov = ToolGovernor(registry, budget=budget, tracker=tracker)

    # Execute 1: consumes 1 tool call
    gov.execute("action", {"name": "step1"}, state_hash_at_call="s0")
    assert budget.tool_calls == 1

    # Execute 2: consumes 2nd tool call
    gov.execute("action", {"name": "step1"}, state_hash_at_call="s0")
    assert budget.tool_calls == 2

    # Execute 3: BLOCKED duplicate!
    blocked_res = gov.execute("action", {"name": "step1"}, state_hash_at_call="s0")
    assert blocked_res["status"] == "blocked"

    # Budget MUST still be exactly 2 (blocked call did not consume tool call budget)
    assert budget.tool_calls == 2
    assert budget.remaining_budget()["remaining_tool_calls"] == 3


def test_successful_tool_updates_budget_and_receipt() -> None:
    from tasksentry.core.receipt import TaskReceipt

    registry = ToolRegistry()

    def ping() -> str:
        return "pong"

    registry.register(Tool(name="ping", input_model=BaseModel, callable=ping))
    budget = Budget(max_tool_calls=10)
    gov = ToolGovernor(registry, budget=budget)

    gov.execute("ping", {})
    gov.execute("ping", {})

    receipt = TaskReceipt(
        task_id="task_001",
        final_status="completed",
        budget_usage=budget.usage_summary(),
        tool_calls=budget.tool_calls,
        duplicate_calls_blocked=gov.blocked_duplicates_count,
        controller_penalty=gov.controller_penalty_total,
    )

    assert receipt.tool_calls == 2
    assert receipt.budget_usage["tool_calls"] == 2
    assert receipt.duplicate_calls_blocked == 0
    assert receipt.controller_penalty == 0.0
