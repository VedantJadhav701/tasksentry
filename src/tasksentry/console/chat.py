"""Chat orchestration translating user conversation requests into governed agent tasks."""

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.console.approvals import default_approval_manager
from tasksentry.console.routing import default_audit_log
from tasksentry.console.runs import ConsoleRun, default_run_manager
from tasksentry.storage.sqlite import SQLiteReceiptStore


class ChatBudgetConfig(BaseModel):
    """Budget limits passed via chat task submission."""

    model_config = ConfigDict(extra="ignore")

    max_tokens: int = 60000
    max_tool_calls: int = 15
    max_cost_usd: float = 0.50
    max_wall_time_seconds: float = 300.0


class ChatTaskRequest(BaseModel):
    """Request payload for POST /api/chat/tasks."""

    model_config = ConfigDict(extra="ignore")

    message: str
    agent: str = "semantic-router"
    routine_model: str = "qwen2.5:3b"
    reasoning_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    budget: ChatBudgetConfig = Field(default_factory=ChatBudgetConfig)
    allow_writes: bool = False
    mock_mode: bool = False


class ChatSessionManager:
    """Manages chat conversation logs and maps tasks to active runs."""

    def __init__(self) -> None:
        self.run_manager = default_run_manager
        self._conversations: dict[str, list[dict[str, Any]]] = {}

    def submit_task(self, req: ChatTaskRequest) -> ConsoleRun:
        task_id = f"task_{uuid.uuid4().hex[:8]}"

        # Record initial user message
        self._conversations.setdefault(task_id, []).append(
            {
                "role": "user",
                "content": req.message,
                "timestamp": time.time(),
            }
        )

        b_dict = req.budget.model_dump()
        run = self.run_manager.create_run(
            task_id=task_id,
            goal=req.message,
            budget_cfg=b_dict,
            allow_writes=req.allow_writes,
            routine_model=req.routine_model,
            reasoning_model=req.reasoning_model,
            mock_mode=req.mock_mode,
            approval_manager=default_approval_manager,
            audit_log=default_audit_log,
            store=SQLiteReceiptStore("tasksentry.db"),
        )

        # Launch execution in background thread
        self.run_manager.start_execution(run)
        return run

    def get_messages(self, task_id: str) -> list[dict[str, Any]]:
        return list(self._conversations.get(task_id, []))


default_chat_manager = ChatSessionManager()
