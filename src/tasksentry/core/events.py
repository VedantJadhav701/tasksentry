"""Event definitions for TaskSentry control plane and monitoring."""

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    """Event types emitted during task execution, governance, and budget tracking."""

    TOOL_REGISTERED = "TOOL_REGISTERED"
    TOOL_VALIDATION_FAILED = "TOOL_VALIDATION_FAILED"
    TOOL_BLOCKED_DUPLICATE = "TOOL_BLOCKED_DUPLICATE"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_ERROR = "TOOL_ERROR"
    TOOL_SUCCESS = "TOOL_SUCCESS"
    BUDGET_WARNING = "BUDGET_WARNING"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    BUDGET_HARD_LIMIT = "BUDGET_HARD_LIMIT"
    RETRY = "RETRY"
    RETRY_EXEMPTED = "RETRY_EXEMPTED"


# Convenience constants for direct imports
TOOL_REGISTERED = EventType.TOOL_REGISTERED
TOOL_VALIDATION_FAILED = EventType.TOOL_VALIDATION_FAILED
TOOL_BLOCKED_DUPLICATE = EventType.TOOL_BLOCKED_DUPLICATE
TOOL_TIMEOUT = EventType.TOOL_TIMEOUT
TOOL_ERROR = EventType.TOOL_ERROR
TOOL_SUCCESS = EventType.TOOL_SUCCESS
BUDGET_WARNING = EventType.BUDGET_WARNING
BUDGET_EXCEEDED = EventType.BUDGET_EXCEEDED
BUDGET_HARD_LIMIT = EventType.BUDGET_HARD_LIMIT
RETRY = EventType.RETRY
RETRY_EXEMPTED = EventType.RETRY_EXEMPTED


class Event(BaseModel):
    """An observable lifecycle or telemetry event in TaskSentry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: EventType | str
    timestamp: float = Field(default_factory=time.time)
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
