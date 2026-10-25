"""Task execution receipts for post-run telemetry, auditing, and accounting."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskReceipt(BaseModel):
    """Execution receipt summarizing task cost, latency, reliability, and governance.

    Attributes:
        task_id: ID of the executed task.
        final_status: final outcome ("completed", "failed", "stopped", "budget_exceeded", etc.).
        budget_usage: usage metrics across tokens, cost, calls, and wall time.
        pricing_model: pricing configuration identifier or details used for cost calculation.
        tool_calls: total tool invocations attempted or executed.
        duplicate_calls_blocked: count of duplicate calls blocked by governor.
        retries: count of retries attempted.
        retry_exemptions: count of retry attempts granted exemption from repetition penalty.
        risk_events: risk-policy violations or safety approvals recorded.
        warnings: collected warnings (e.g. budget warnings).
        errors: collected errors encountered during task execution.
        controller_penalty: cumulative controller penalty for blocked actions.
        wall_time_seconds: total elapsed wall clock duration.
        metadata: additional task-specific receipt metadata.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    final_status: str = "completed"
    budget_usage: dict[str, Any] = Field(default_factory=dict)
    pricing_model: str | dict[str, Any] | None = None
    tool_calls: int = 0
    duplicate_calls_blocked: int = 0
    retries: int = 0
    retry_exemptions: int = 0
    risk_events: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    controller_penalty: float = 0.0
    wall_time_seconds: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
