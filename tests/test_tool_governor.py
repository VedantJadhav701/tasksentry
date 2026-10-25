"""Unit tests for the TaskSentry ToolGovernor."""

from pydantic import BaseModel

from tasksentry.budget.budget import Budget
from tasksentry.core.contract import SafetyRules
from tasksentry.core.events import TOOL_BLOCKED_DUPLICATE, TOOL_VALIDATION_FAILED
from tasksentry.core.state import CanonicalState
from tasksentry.math.progress import ProgressConfig, ProgressTracker, RetryExemptions
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import Tool, ToolRegistry


def test_allowed_tool_executes() -> None:
    reg = ToolRegistry()

    def my_echo(text: str) -> str:
        return text

    reg.register(Tool(name="echo", input_model=BaseModel, callable=my_echo))
    gov = ToolGovernor(reg)
    res = gov.execute("echo", {"text": "hello"})
    assert res["status"] == "success"
    assert res["result"] == "hello"


def test_disallowed_tool_blocked() -> None:
    reg = ToolRegistry()

    def dummy() -> str:
        return "ok"

    reg.register(Tool(name="allowed_tool", input_model=BaseModel, callable=dummy))
    reg.register(Tool(name="forbidden_tool", input_model=BaseModel, callable=dummy))

    safety = SafetyRules(allowed_tools=("allowed_tool",))
    gov = ToolGovernor(reg, safety=safety)

    res = gov.execute("forbidden_tool", {})
    assert res["status"] == "blocked"
    assert res["reason"] == "tool_not_allowed"


def test_invalid_arguments_blocked() -> None:
    class StrictInput(BaseModel):
        num: int

    reg = ToolRegistry()
    called = False

    def guarded(num: int) -> int:
        nonlocal called
        called = True
        return num

    reg.register(Tool(name="guarded", input_model=StrictInput, callable=guarded))
    gov = ToolGovernor(reg)

    res = gov.execute("guarded", {"num": "not_an_int"})
    assert res["status"] == "error"
    assert res["reason"] == "validation_failed"
    assert not called
    assert any(e.type == TOOL_VALIDATION_FAILED for e in gov.events)


def test_exact_duplicate_blocked_after_threshold() -> None:
    class DummyInput(BaseModel):
        cmd: str

    reg = ToolRegistry()

    def side_effect_tool(cmd: str) -> str:
        return f"executed {cmd}"

    # non-idempotent tool
    reg.register(
        Tool(name="run_cmd", input_model=DummyInput, callable=side_effect_tool, idempotent=False)
    )

    tracker = ProgressTracker(config=ProgressConfig(block_threshold=2))
    gov = ToolGovernor(reg, tracker=tracker)

    # Call 1: success
    res1 = gov.execute("run_cmd", {"cmd": "build"}, state_hash_at_call="state_v1")
    assert res1["status"] == "success"

    # Call 2: success
    res2 = gov.execute("run_cmd", {"cmd": "build"}, state_hash_at_call="state_v1")
    assert res2["status"] == "success"

    # Call 3: duplicate count is now 2 >= threshold 2 -> blocked!
    res3 = gov.execute("run_cmd", {"cmd": "build"}, state_hash_at_call="state_v1")
    assert res3["status"] == "blocked"
    assert res3["reason"] == "duplicate_action"
    assert res3["suggested_next_action"] == "replan"
    assert any(e.type == TOOL_BLOCKED_DUPLICATE for e in gov.events)
    assert gov.blocked_duplicates_count == 1
    assert gov.controller_penalty_total == -0.5


def test_run_tests_before_after_state_change_not_duplicate() -> None:
    class TestInput(BaseModel):
        suite: str

    reg = ToolRegistry()

    def run_tests(suite: str) -> str:
        return f"tests {suite} passed"

    reg.register(
        Tool(name="run_tests", input_model=TestInput, callable=run_tests, idempotent=False)
    )

    tracker = ProgressTracker(config=ProgressConfig(block_threshold=2))
    gov = ToolGovernor(reg, tracker=tracker)

    state_before = CanonicalState(goal="fix bug", world={"files_changed": []})
    state_after = CanonicalState(goal="fix bug", world={"files_changed": ["fix.py"]})

    # Call 1 before edit
    res1 = gov.execute("run_tests", {"suite": "unit"}, canonical_state=state_before)
    assert res1["status"] == "success"

    # Call 2 before edit (fingerprint count for state_before becomes 2)
    res2 = gov.execute("run_tests", {"suite": "unit"}, canonical_state=state_before)
    assert res2["status"] == "success"

    # Call after edit (different canonical state hash -> different fingerprint!)
    res3 = gov.execute("run_tests", {"suite": "unit"}, canonical_state=state_after)
    assert res3["status"] == "success"


def test_transient_failure_retry_exempted() -> None:
    class DummyInput(BaseModel):
        op: str

    reg = ToolRegistry()

    def flaky_tool(op: str) -> str:
        return "recovered"

    reg.register(Tool(name="flaky", input_model=DummyInput, callable=flaky_tool, idempotent=False))
    tracker = ProgressTracker(config=ProgressConfig(block_threshold=2))
    gov = ToolGovernor(reg, tracker=tracker)

    gov.execute("flaky", {"op": "sync"}, state_hash_at_call="s1")
    gov.execute("flaky", {"op": "sync"}, state_hash_at_call="s1")

    # 3rd call with transient failure exemption must NOT be blocked
    exempt = RetryExemptions(previous_transient_failure=True)
    res = gov.execute("flaky", {"op": "sync"}, state_hash_at_call="s1", exemptions=exempt)
    assert res["status"] == "success"


def test_idempotent_retry_exempted() -> None:
    class ReadInput(BaseModel):
        path: str

    reg = ToolRegistry()

    def read_file(path: str) -> str:
        return "contents"

    # Tool is explicitly idempotent
    reg.register(Tool(name="read_file", input_model=ReadInput, callable=read_file, idempotent=True))
    tracker = ProgressTracker(config=ProgressConfig(block_threshold=2))
    gov = ToolGovernor(reg, tracker=tracker)

    # Calls should never be blocked by duplicate rule
    gov.execute("read_file", {"path": "a.txt"}, state_hash_at_call="s1")
    gov.execute("read_file", {"path": "a.txt"}, state_hash_at_call="s1")
    res = gov.execute("read_file", {"path": "a.txt"}, state_hash_at_call="s1")
    assert res["status"] == "success"


def test_budget_prevents_execution() -> None:
    reg = ToolRegistry()

    def simple() -> str:
        return "done"

    reg.register(Tool(name="simple", input_model=BaseModel, callable=simple))
    budget = Budget(max_tool_calls=1)
    gov = ToolGovernor(reg, budget=budget)

    res1 = gov.execute("simple", {})
    assert res1["status"] == "success"
    assert budget.tool_calls == 1

    # Second call exceeds tool call budget
    res2 = gov.execute("simple", {})
    assert res2["status"] == "blocked"
    assert res2["reason"] == "budget_exceeded"
    # Budget tool calls should remain 1 because blocked call does not execute
    assert budget.tool_calls == 1


def test_risk_policy_blocks_destructive_tool() -> None:
    reg = ToolRegistry()

    def wipe_db() -> str:
        return "wiped"

    reg.register(Tool(name="wipe_db", input_model=BaseModel, callable=wipe_db, risk="destructive"))
    safety = SafetyRules(max_risk=0.2)
    gov = ToolGovernor(reg, safety=safety)

    res = gov.execute("wipe_db", {})
    assert res["status"] == "blocked"
    assert res["reason"] == "risk_limit_exceeded"


def test_third_blocked_duplicate_escalates() -> None:
    reg = ToolRegistry()

    def act() -> str:
        return "ok"

    reg.register(Tool(name="act", input_model=BaseModel, callable=act, idempotent=False))
    tracker = ProgressTracker(config=ProgressConfig(block_threshold=1, escalate_after_blocks=3))
    gov = ToolGovernor(reg, tracker=tracker)

    # Action 1 executed
    gov.execute("act", {}, state_hash_at_call="s0")

    # Block 1
    b1 = gov.execute("act", {}, state_hash_at_call="s0")
    assert b1["status"] == "blocked"
    assert b1["escalate"] is False

    # Block 2
    b2 = gov.execute("act", {}, state_hash_at_call="s0")
    assert b2["status"] == "blocked"
    assert b2["escalate"] is False

    # Block 3 triggers escalation
    b3 = gov.execute("act", {}, state_hash_at_call="s0")
    assert b3["status"] == "blocked"
    assert b3["escalate"] is True
    assert b3["suggested_next_action"] == "escalate"
