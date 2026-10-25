"""Data models and abstractions for TaskSentry benchmark tasks."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.core.contract import (
    BudgetLimits,
    Milestone,
    SuccessCriterion,
    TaskContract,
)


class BenchmarkTask(BaseModel):
    """Specification of an offline deterministic benchmark task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    family: str
    goal: str
    success_criteria: list[SuccessCriterion]
    milestones: list[Milestone] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    budget_limits: BudgetLimits = Field(default_factory=BudgetLimits)
    injected_failures: dict[str, Any] = Field(default_factory=dict)
    expected_outcome: dict[str, Any] = Field(default_factory=dict)
    fake_actions: list[dict[str, Any]] = Field(default_factory=list)
    premature_claim_step: int | None = None
    loop_trigger_step: int | None = None

    def to_contract(self) -> TaskContract:
        """Convert benchmark task specification into an executable TaskContract."""
        return TaskContract(
            task_id=self.task_id,
            goal=self.goal,
            success_criteria=self.success_criteria,
            milestones=self.milestones,
            budget=self.budget_limits,
        )
