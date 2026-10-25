"""Unit tests for the ActionGate regulating tool calls and completion claims."""

from pydantic import BaseModel

from tasksentry.core.contract import SuccessCriterion, TaskContract
from tasksentry.harness.action_gate import ActionGate
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import Tool, ToolRegistry


def _contract_with_criterion(min_val: int = 10) -> TaskContract:
    c = SuccessCriterion(id="gate1", verifier="numeric_range", config={"value": 15, "min": min_val})
    return TaskContract(goal="Complete gate", success_criteria=[c])


def test_action_gate_allows_valid_tool_call() -> None:
    reg = ToolRegistry()

    def my_tool() -> str:
        return "ok"

    reg.register(Tool(name="my_tool", input_model=BaseModel, callable=my_tool))
    gov = ToolGovernor(reg)
    contract = _contract_with_criterion()
    gate = ActionGate(gov, contract)

    action = {"type": "tool_call", "tool": "my_tool", "arguments": {}}
    verdict = gate.evaluate_action(action)
    assert verdict.allowed is True
    assert verdict.is_completion_claim is False


def test_action_gate_rejects_missing_tool() -> None:
    reg = ToolRegistry()
    gov = ToolGovernor(reg)
    contract = _contract_with_criterion()
    gate = ActionGate(gov, contract)

    action = {"type": "tool_call", "tool": "missing_tool", "arguments": {}}
    verdict = gate.evaluate_action(action)
    assert verdict.allowed is False
    assert "not found" in str(verdict.rejection_reason)


def test_action_gate_rejects_premature_completion() -> None:
    # Contract requires value >= 20, but criterion config has value 15 -> will fail!
    contract = _contract_with_criterion(min_val=20)
    reg = ToolRegistry()
    gov = ToolGovernor(reg)
    gate = ActionGate(gov, contract)

    action = {"type": "complete_task", "answer": "I am done"}
    verdict = gate.evaluate_action(action)

    assert verdict.is_completion_claim is True
    assert verdict.allowed is False
    assert "rejected" in str(verdict.rejection_reason).lower()
    assert len(gate.events) == 1
    assert gate.events[0].type == "VERIFICATION_FAILED"


def test_action_gate_allows_verified_completion() -> None:
    # Criterion has value 15, min_val 10 -> will pass!
    contract = _contract_with_criterion(min_val=10)
    reg = ToolRegistry()
    gov = ToolGovernor(reg)
    gate = ActionGate(gov, contract)

    action = {"type": "complete_task", "answer": "All verified"}
    verdict = gate.evaluate_action(action)

    assert verdict.is_completion_claim is True
    assert verdict.allowed is True
    assert verdict.rejection_reason is None
