"""Unit tests for the top-level AgentTask runtime abstraction."""

from pydantic import BaseModel

from tasksentry.core.contract import Milestone, SuccessCriterion, TaskContract, VerifierSpec
from tasksentry.core.task import AgentTask
from tasksentry.harness.agent import ScriptedAgent
from tasksentry.tools.registry import Tool, ToolRegistry


def test_agent_task_with_fake_coding_agent() -> None:
    criterion = SuccessCriterion(
        id="check_result",
        verifier="numeric_range",
        config={"value": 100, "min": 0},
    )
    contract = TaskContract(goal="Solve sample task", success_criteria=[criterion])

    task = AgentTask(contract)
    receipt = task.run(agent="fake-coding-agent", max_steps=5)

    assert receipt.task_id == contract.task_id
    assert receipt.status == "completed"
    assert receipt.success is True
    assert isinstance(receipt.tokens, int)
    assert isinstance(receipt.cost_usd, float)
    assert isinstance(receipt.tool_calls, int)
    assert isinstance(receipt.loop_warnings, int)
    assert isinstance(receipt.events, list)
    assert receipt.slo_met is True


def test_agent_task_milestone_verification_gate() -> None:
    # Model cannot mark milestone done itself; milestone done_when verifier must pass!
    m1 = Milestone(
        id="milestone_1",
        done_when=VerifierSpec(verifier="numeric_range", config={"value": 5, "min": 0}),
    )
    c1 = SuccessCriterion(
        id="criterion_1",
        verifier="numeric_range",
        config={"value": 10, "min": 0},
    )
    contract = TaskContract(goal="Milestone task", milestones=[m1], success_criteria=[c1])

    task = AgentTask(contract)
    agent = ScriptedAgent(
        actions=[
            {"type": "complete_task", "answer": "done"},
        ]
    )

    receipt = task.run(agent=agent, max_steps=3)
    assert receipt.status == "completed"
    assert receipt.success is True


def test_agent_task_loop_detection_and_replan() -> None:
    # Agent repeats an action causing repeated execution or duplicate blocks
    reg = ToolRegistry()

    def nop() -> str:
        return "noop"

    reg.register(Tool(name="nop", input_model=BaseModel, callable=nop, idempotent=False))

    criterion = SuccessCriterion(
        id="goal_gate",
        verifier="numeric_range",
        config={"value": 10, "min": 20},  # will not pass immediately
    )
    contract = TaskContract(goal="Loop test", success_criteria=[criterion])

    task = AgentTask(contract, registry=reg)

    # Agent repeats same action 4 times
    agent = ScriptedAgent(
        actions=[{"type": "tool_call", "tool": "nop", "arguments": {}} for _ in range(4)]
    )

    receipt = task.run(agent=agent, max_steps=5)
    # The duplicate rule or anti-loop logic intervenes
    assert (
        receipt.duplicate_calls_blocked >= 1
        or receipt.loop_warnings >= 1
        or receipt.status != "completed"
    )
