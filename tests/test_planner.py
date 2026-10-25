"""Unit tests for the task planner and milestone scheduling."""

from tasksentry.core.contract import Milestone, SuccessCriterion, TaskContract, VerifierSpec
from tasksentry.harness.planner import Planner


def _sample_contract() -> TaskContract:
    c1 = SuccessCriterion(id="gate1", verifier="numeric_range", config={"value": 1, "min": 0})
    m1 = Milestone(
        id="m1_setup",
        done_when=VerifierSpec(verifier="numeric_range", config={"value": 1, "min": 0}),
    )
    m2 = Milestone(
        id="m2_execute",
        done_when=VerifierSpec(verifier="numeric_range", config={"value": 1, "min": 0}),
    )
    return TaskContract(
        goal="Complete sample deployment",
        success_criteria=[c1],
        milestones=[m1, m2],
    )


def test_initial_plan_creation() -> None:
    contract = _sample_contract()
    planner = Planner(contract)

    plan = planner.get_plan()
    assert plan.milestones == ["m1_setup", "m2_execute"]
    assert plan.current_milestone == "m1_setup"
    assert "m1_setup" in plan.next_action
    assert plan.completed_milestones == []
    assert plan.replan_count == 0


def test_milestone_tracking() -> None:
    contract = _sample_contract()
    planner = Planner(contract)

    # Complete first milestone
    plan = planner.update_completed({"m1_setup"})
    assert plan.completed_milestones == ["m1_setup"]
    assert plan.current_milestone == "m2_execute"
    assert "m2_execute" in plan.next_action

    # Complete second milestone
    plan2 = planner.update_completed({"m2_execute"})
    assert plan2.completed_milestones == ["m1_setup", "m2_execute"]
    assert plan2.current_milestone is None
    assert "All milestones satisfied" in plan2.next_action


def test_replan_preserves_completed_milestones() -> None:
    contract = _sample_contract()
    planner = Planner(contract)

    planner.update_completed({"m1_setup"})

    # Trigger replan due to failure in m2
    revised = planner.replan("Deployment container crashed")
    assert revised.replan_count == 1
    assert "m1_setup" in revised.completed_milestones
    assert revised.current_milestone == "m2_execute"
    assert "Deployment container crashed" in revised.next_action


def test_replan_does_not_erase_contract_criteria() -> None:
    contract = _sample_contract()
    planner = Planner(contract)

    planner.replan("Strategy failed")
    # All criteria remain preserved on contract
    assert len(planner.contract.success_criteria) == 1
    assert planner.contract.success_criteria[0].id == "gate1"
