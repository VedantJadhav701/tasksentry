"""Unit tests for the CASE agent runtime loop."""

from pydantic import BaseModel

from tasksentry.budget.budget import Budget
from tasksentry.core.contract import SuccessCriterion, TaskContract
from tasksentry.core.runtime import CASERuntime
from tasksentry.harness.agent import ScriptedAgent
from tasksentry.tools.registry import Tool, ToolRegistry


def test_runtime_full_successful_task() -> None:
    reg = ToolRegistry()

    def create_artifact() -> str:
        return "artifact_created"

    reg.register(Tool(name="create_artifact", input_model=BaseModel, callable=create_artifact))

    criterion = SuccessCriterion(
        id="check_success",
        verifier="numeric_range",
        config={"value": 100, "min": 50},
    )
    contract = TaskContract(goal="Build artifact", success_criteria=[criterion])

    runtime = CASERuntime(contract, registry=reg)

    agent = ScriptedAgent(
        actions=[
            {"type": "tool_call", "tool": "create_artifact", "arguments": {}},
            {"type": "complete_task", "answer": "Artifact verified"},
        ]
    )

    receipt = runtime.run_loop(agent, max_steps=5)

    assert receipt.status == "completed"
    assert receipt.success is True
    assert receipt.final_answer is not None
    assert receipt.tool_calls == 1
    assert receipt.slo_met is True


def test_runtime_premature_completion_rejected() -> None:
    # Criterion has value 10, min 50 -> verification fails!
    criterion = SuccessCriterion(
        id="gate_strict",
        verifier="numeric_range",
        config={"value": 10, "min": 50},
    )
    contract = TaskContract(goal="Strict task", success_criteria=[criterion])

    runtime = CASERuntime(contract)

    # Agent immediately claims completion without fulfilling criterion
    agent = ScriptedAgent(
        actions=[
            {"type": "complete_task", "answer": "I'm done early"},
        ]
    )

    receipt = runtime.run_loop(agent, max_steps=2)

    assert receipt.status != "completed"
    assert receipt.success is False
    assert any(e["type"] == "VERIFICATION_FAILED" for e in receipt.events)


def test_runtime_exceeds_budget_stops() -> None:
    reg = ToolRegistry()

    def do_step() -> str:
        return "step"

    reg.register(Tool(name="do_step", input_model=BaseModel, callable=do_step))

    criterion = SuccessCriterion(
        id="never_reached",
        verifier="numeric_range",
        config={"value": 10, "min": 50},
    )
    contract = TaskContract(goal="Budget test", success_criteria=[criterion])

    budget = Budget(max_tool_calls=2)
    runtime = CASERuntime(contract, registry=reg, budget=budget)

    # Agent attempts 5 tool calls
    agent = ScriptedAgent(
        actions=[{"type": "tool_call", "tool": "do_step", "arguments": {}} for _ in range(5)]
    )

    receipt = runtime.run_loop(agent, max_steps=5)

    assert receipt.status == "stopped"
    assert receipt.success is False
    assert receipt.tool_calls == 2
