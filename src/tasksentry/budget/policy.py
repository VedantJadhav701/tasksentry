"""Budget enforcement policies (hard vs. soft limits, warning thresholds)."""

from pydantic import BaseModel, ConfigDict, Field


class BudgetPolicy(BaseModel):
    """Enforcement policy for task resource limits.

    Attributes:
        hard_limits: If True, exceeding any limit prevents subsequent actions by raising
            BudgetExceededError. If False, soft limits allow in-flight actions to complete.
        warning_threshold: Fractional consumption ratio (0.0 to 1.0) at which BUDGET_WARNING
            is emitted. Default is 0.80 (80%).
        allow_soft_overflow: Whether in-flight calls that marginally exceed limits are allowed
            to finish before stopping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hard_limits: bool = True
    warning_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    allow_soft_overflow: bool = False
