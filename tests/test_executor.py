"""Unit tests for the step executor and APG accounting."""

import time

from pydantic import BaseModel

from tasksentry.budget.budget import Budget
from tasksentry.core.state import CanonicalState
from tasksentry.harness.executor import Executor
from tasksentry.math.progress import ProgressTracker
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import Tool, ToolRegistry
from tasksentry.tools.sandbox import Sandbox


def _sample_slow_tool() -> str:
    time.sleep(2.0)
    return "done"


def test_executor_successful_step() -> None:
    reg = ToolRegistry()

    def greet(name: str) -> str:
        return f"Hello, {name}"

    reg.register(Tool(name="greet", input_model=BaseModel, callable=greet))

    budget = Budget(max_tool_calls=5)
    tracker = ProgressTracker()
    gov = ToolGovernor(reg, budget=budget, tracker=tracker)
    executor = Executor(gov, tracker, budget=budget)

    state = CanonicalState(goal="Greet user")
    action = {"tool": "greet", "arguments": {"name": "Bob"}}

    res, _new_state = executor.execute_step(action, state, cost_usd=0.01, tokens=50)

    assert res.status == "success"
    assert res.observation == "Hello, Bob"
    assert res.cost_usd == 0.01
    assert res.tokens == 50
    assert budget.tool_calls == 1
    assert budget.total_tokens == 50
    assert res.state_hash_before == state.state_hash()


def test_executor_state_hash_update() -> None:
    reg = ToolRegistry()

    def do_work() -> str:
        return "work done"

    reg.register(Tool(name="do_work", input_model=BaseModel, callable=do_work))

    tracker = ProgressTracker()
    gov = ToolGovernor(reg, tracker=tracker)
    executor = Executor(gov, tracker)

    state = CanonicalState(goal="Do work", world={"files_changed": []})
    action = {"tool": "do_work", "arguments": {}}

    context = {"new_world": {"files_changed": ["work.txt"]}}
    res, new_state = executor.execute_step(action, state, context=context)

    assert res.status == "success"
    assert res.state_hash_before != res.state_hash_after
    assert new_state.world["files_changed"] == ["work.txt"]


def test_executor_failing_step() -> None:
    reg = ToolRegistry()

    def buggy() -> str:
        raise RuntimeError("database crash")

    reg.register(Tool(name="buggy", input_model=BaseModel, callable=buggy))

    tracker = ProgressTracker()
    gov = ToolGovernor(reg, tracker=tracker)
    executor = Executor(gov, tracker)

    state = CanonicalState(goal="Test failure")
    action = {"tool": "buggy", "arguments": {}}

    res, _new_state = executor.execute_step(action, state)
    assert res.status == "error"
    assert "database crash" in res.observation


def test_executor_tool_timeout() -> None:
    # Use process sandbox with low timeout
    reg = ToolRegistry()
    reg.register(
        Tool(name="slow", input_model=BaseModel, callable=_sample_slow_tool, timeout_seconds=0.2)
    )

    sandbox = Sandbox(mode="process")
    tracker = ProgressTracker()
    gov = ToolGovernor(reg, tracker=tracker, sandbox=sandbox)
    executor = Executor(gov, tracker)

    state = CanonicalState(goal="Test timeout")
    action = {"tool": "slow", "arguments": {}}

    res, _new_state = executor.execute_step(action, state)
    assert res.status == "timeout"
    assert "Timeout:" in res.observation
