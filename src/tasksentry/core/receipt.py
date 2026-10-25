"""Task execution receipts for post-run telemetry, auditing, and accounting."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskReceipt(BaseModel):
    """Execution receipt summarizing task cost, latency, reliability, and governance.

    Attributes:
        task_id: ID of the executed task.
        status: final status ('completed', 'failed', 'stopped', 'escalated').
        final_status: alias for status preserving Phase 2 compatibility.
        success: whether all required verification gates passed and goal was achieved.
        tokens: total token count consumed.
        cost_usd: monetary cost in USD.
        llm_calls: count of LLM queries.
        tool_calls: total tool invocations attempted or executed.
        retries: count of retries attempted.
        wall_time_seconds: total elapsed wall clock duration.
        duplicate_calls_blocked: count of duplicate calls blocked by governor.
        controller_penalty: cumulative controller penalty for blocked actions.
        loop_warnings: count of anti-loop warnings emitted.
        verification_results: results of success criteria and milestone verifications.
        waste_report: breakdown of wasted steps, repetition penalties, and overhead.
        events: sequence of lifecycle events emitted during run.
        final_answer: optional textual completion output.
        slo_met: whether cost, latency, and quality objectives were met.
        retry_exemptions: count of retry attempts granted exemption.
        budget_usage: dictionary summary of budget consumption.
        pricing_model: pricing configuration identifier or details.
        risk_events: risk-policy violations or safety approvals recorded.
        warnings: collected warning messages.
        errors: collected error messages.
        metadata: additional task-specific receipt metadata.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    status: str = "completed"
    final_status: str = "completed"
    success: bool = True
    tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    wall_time_seconds: float = 0.0
    duplicate_calls_blocked: int = 0
    controller_penalty: float = 0.0
    loop_warnings: int = 0
    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    waste_report: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str | None = None
    slo_met: bool = True
    retry_exemptions: int = 0
    budget_usage: dict[str, Any] = Field(default_factory=dict)
    pricing_model: str | dict[str, Any] | None = None
    risk_events: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _sync_status(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "status" in data and "final_status" not in data:
                data["final_status"] = data["status"]
            elif "final_status" in data and "status" not in data:
                data["status"] = data["final_status"]
        return data
