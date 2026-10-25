"""Task planner: plan generation, milestone tracking, and replanning."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.core.contract import TaskContract


class Plan(BaseModel):
    """Structured plan outlining milestones and active execution target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    milestones: list[str]
    current_milestone: str | None
    next_action: str
    reason: str
    completed_milestones: list[str] = Field(default_factory=list)
    replan_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to standard planner output dictionary."""
        return {
            "milestones": self.milestones,
            "current_milestone": self.current_milestone or "",
            "next_action": self.next_action,
            "reason": self.reason,
            "completed_milestones": self.completed_milestones,
            "replan_count": self.replan_count,
        }


class Planner:
    """Manages milestone scheduling, task decomposition, and failure replanning.

    Enforces invariants:
    1. Preserves completed milestones during replanning.
    2. Does not permit erasing required success criteria or objective gates.
    """

    def __init__(self, contract: TaskContract) -> None:
        self.contract = contract
        self._completed_milestones: set[str] = set()
        self._replan_count: int = 0
        self._current_plan: Plan = self.create_initial_plan()

    def create_initial_plan(self) -> Plan:
        """Formulate initial plan based on contract milestones and criteria."""
        all_milestones = [m.id for m in self.contract.milestones]
        if not all_milestones:
            # Fall back to criteria IDs if no explicit milestones defined
            all_milestones = [c.id for c in self.contract.success_criteria]

        active_milestone = all_milestones[0] if all_milestones else None
        next_act = (
            f"Work on milestone {active_milestone}"
            if active_milestone
            else f"Fulfill goal: {self.contract.goal}"
        )

        plan = Plan(
            milestones=all_milestones,
            current_milestone=active_milestone,
            next_action=next_act,
            reason="Initial task plan constructed from contract gates.",
            completed_milestones=[],
            replan_count=0,
        )
        self._current_plan = plan
        return plan

    def update_completed(self, completed: set[str] | frozenset[str]) -> Plan:
        """Record completed milestones and advance active target."""
        self._completed_milestones.update(completed)

        uncompleted = [
            m for m in self._current_plan.milestones if m not in self._completed_milestones
        ]
        next_active = uncompleted[0] if uncompleted else None

        next_act = (
            f"Work on milestone {next_active}"
            if next_active
            else "All milestones satisfied. Verify success criteria and complete task."
        )

        reason = (
            f"Advanced to milestone {next_active}"
            if next_active
            else "All milestones complete; preparing for final verification."
        )

        plan = Plan(
            milestones=self._current_plan.milestones,
            current_milestone=next_active,
            next_action=next_act,
            reason=reason,
            completed_milestones=sorted(self._completed_milestones),
            replan_count=self._replan_count,
        )
        self._current_plan = plan
        return plan

    def replan(self, failure_reason: str, state_summary: str = "") -> Plan:
        """Generate a revised plan while preserving completed milestones.

        Invariants:
        - Already completed milestones remain completed.
        - Contract success criteria cannot be removed or altered.
        """
        self._replan_count += 1

        uncompleted = [
            m for m in self._current_plan.milestones if m not in self._completed_milestones
        ]
        next_active = uncompleted[0] if uncompleted else None

        detail = f" ({state_summary})" if state_summary else ""
        next_act = (
            f"Alternative approach for {next_active}: {failure_reason}{detail}"
            if next_active
            else "Re-evaluate failed criteria"
        )

        plan = Plan(
            milestones=self._current_plan.milestones,
            current_milestone=next_active,
            next_action=next_act,
            reason=f"Replanning triggered: {failure_reason}",
            completed_milestones=sorted(self._completed_milestones),
            replan_count=self._replan_count,
        )
        self._current_plan = plan
        return plan

    def get_plan(self) -> Plan:
        """Return the current active plan."""
        return self._current_plan
