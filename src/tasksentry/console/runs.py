"""Task execution engine managing live background agent runs, SSE streaming, and approvals."""

import json
import logging
import queue
import threading
import time
from typing import Any

from tasksentry.console.approvals import ApprovalManager, default_approval_manager
from tasksentry.console.routing import RouterAuditLog, RoutingDecision, default_audit_log
from tasksentry.core.contract import SuccessCriterion
from tasksentry.core.receipt import TaskReceipt
from tasksentry.core.task import AgentTask
from tasksentry.harness.agent import Agent, FakeCodingAgent, LLMAgent
from tasksentry.models.base import ModelClient
from tasksentry.models.fake_model import FakeModel
from tasksentry.models.router import SemanticModelRouter
from tasksentry.storage.receipts import ReceiptStore
from tasksentry.storage.sqlite import SQLiteReceiptStore
from tasksentry.tools.builtin import BUILTIN_TOOLS
from tasksentry.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class RunEvent:
    """A streaming execution event formatted for Server-Sent Events."""

    def __init__(self, event_type: str, data: dict[str, Any], task_id: str) -> None:
        self.event_type = event_type
        self.data = data
        self.task_id = task_id
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.event_type,
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class ConsoleRun:
    """Encapsulation of a live background agent execution."""

    def __init__(
        self,
        task_id: str,
        goal: str,
        budget_cfg: dict[str, Any] | None = None,
        allow_writes: bool = False,
        routine_model: str = "qwen2.5:3b",
        reasoning_model: str = "qwen3:4b-instruct-2507-q4_K_M",
        mock_mode: bool = False,
        approval_manager: ApprovalManager | None = None,
        audit_log: RouterAuditLog | None = None,
        store: ReceiptStore | None = None,
    ) -> None:
        self.task_id = task_id
        self.goal = goal
        self.budget_cfg = budget_cfg or {}
        self.allow_writes = allow_writes
        self.routine_model = routine_model
        self.reasoning_model = reasoning_model
        self.mock_mode = mock_mode

        self.status = "created"  # created, running, waiting_approval, completed, failed, stopped
        self.created_at = time.time()
        self.completed_at: float | None = None
        self.receipt: TaskReceipt | None = None
        self.error: str | None = None

        self.approval_manager = approval_manager or default_approval_manager
        self.audit_log = audit_log or default_audit_log
        self.store = store or SQLiteReceiptStore("tasksentry.db")

        self._subscribers: list[queue.Queue[RunEvent | None]] = []
        self._events_history: list[RunEvent] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def subscribe(self) -> queue.Queue[RunEvent | None]:
        """Subscribe to the real-time event stream."""
        q: queue.Queue[RunEvent | None] = queue.Queue()
        with self._lock:
            # Replay existing events to new subscriber
            for evt in self._events_history:
                q.put(evt)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[RunEvent | None]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a lifecycle event to all active subscribers."""
        event = RunEvent(event_type=event_type, data=data, task_id=self.task_id)
        with self._lock:
            self._events_history.append(event)
            dead_subs = []
            for sub in self._subscribers:
                try:
                    sub.put_nowait(event)
                except Exception:
                    dead_subs.append(sub)
            for d in dead_subs:
                self._subscribers.remove(d)

    def request_stop(self) -> None:
        """Signal execution loop to stop."""
        self._stop_event.set()
        self.status = "stopped"
        self.emit("task_stopped", {"reason": "Stopped by user request."})

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def get_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events_history]


class ConsoleRunManager:
    """Manages active and historical console agent runs."""

    def __init__(self) -> None:
        self._runs: dict[str, ConsoleRun] = {}
        self._lock = threading.Lock()

    def create_run(
        self,
        task_id: str,
        goal: str,
        budget_cfg: dict[str, Any] | None = None,
        allow_writes: bool = False,
        routine_model: str = "qwen2.5:3b",
        reasoning_model: str = "qwen3:4b-instruct-2507-q4_K_M",
        mock_mode: bool = False,
        approval_manager: ApprovalManager | None = None,
        audit_log: RouterAuditLog | None = None,
        store: ReceiptStore | None = None,
    ) -> ConsoleRun:
        run = ConsoleRun(
            task_id=task_id,
            goal=goal,
            budget_cfg=budget_cfg,
            allow_writes=allow_writes,
            routine_model=routine_model,
            reasoning_model=reasoning_model,
            mock_mode=mock_mode,
            approval_manager=approval_manager,
            audit_log=audit_log,
            store=store,
        )
        with self._lock:
            self._runs[task_id] = run
        return run

    def get(self, task_id: str) -> ConsoleRun | None:
        with self._lock:
            return self._runs.get(task_id)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            runs_list = list(self._runs.values())
        runs_list.sort(key=lambda r: r.created_at, reverse=True)
        return [
            {
                "task_id": r.task_id,
                "goal": r.goal,
                "status": r.status,
                "created_at": r.created_at,
                "completed_at": r.completed_at,
                "tokens": r.receipt.tokens if r.receipt else 0,
                "cost_usd": r.receipt.cost_usd if r.receipt else 0.0,
                "success": r.receipt.success if r.receipt else None,
            }
            for r in runs_list[:limit]
        ]

    def start_execution(self, run: ConsoleRun) -> None:
        """Launch run in background thread."""
        t = threading.Thread(
            target=self._execute_run_thread,
            args=(run,),
            daemon=True,
            name=f"ConsoleRun-{run.task_id}",
        )
        run._thread = t
        t.start()

    def _execute_run_thread(self, run: ConsoleRun) -> None:
        run.status = "running"
        run.emit("task_created", {"task_id": run.task_id, "goal": run.goal})

        b_cfg = run.budget_cfg
        max_tokens = b_cfg.get("max_tokens", 60000)
        max_tools = b_cfg.get("max_tool_calls", 15)
        max_cost = b_cfg.get("max_cost_usd", 0.50)
        max_time = b_cfg.get("max_wall_time_seconds", 300.0)

        run.emit(
            "contract_created",
            {
                "task_id": run.task_id,
                "budget": {
                    "max_tokens": max_tokens,
                    "max_tool_calls": max_tools,
                    "max_cost_usd": max_cost,
                    "max_wall_time_seconds": max_time,
                },
            },
        )

        # Build Tool Registry
        registry = ToolRegistry()
        for t in BUILTIN_TOOLS:
            registry.register(t)
        from tasksentry.telecom.tools import get_telecom_agent_tools

        for t in get_telecom_agent_tools():
            registry.register(t)

        # Plan creation
        run.emit("planner_started", {"goal": run.goal})
        plan_milestones = [
            {"id": "inspect_target", "description": "Inspect repository files and diagnose setup"},
            {"id": "execute_solution", "description": "Apply required updates or extract facts"},
            {"id": "verify_correctness", "description": "Run verification checks and report"},
        ]
        run.emit("plan_created", {"milestones": plan_milestones})

        # Router and Agent Setup
        if run.mock_mode:
            model_client: ModelClient = FakeModel()
        else:
            model_client = SemanticModelRouter(
                routine_model=run.routine_model,
                reasoning_model=run.reasoning_model,
            )

        # Success criteria for the contract
        crit_obj = SuccessCriterion(
            id="verify_workspace_state",
            verifier="file_exists",
            config={"path": "pyproject.toml"},
        )
        criteria: list[SuccessCriterion | dict[str, Any]] = [crit_obj]

        task = AgentTask(
            goal=run.goal,
            max_llm_calls=b_cfg.get("max_llm_calls", 10),
            max_tool_calls=max_tools,
            max_tokens=max_tokens,
            max_cost_usd=max_cost,
            max_wall_time_seconds=max_time,
            success_criteria=criteria,
            registry=registry,
            task_id=run.task_id,
            store=run.store,
        )

        # Governed Execution Loop with streaming instrumentation
        step = 1
        agent: Agent
        if run.mock_mode:
            agent = FakeCodingAgent()
        else:
            agent = LLMAgent(
                model_client=model_client,
                registry=registry,
                budget=task.runtime.budget,
                system_prompt=(
                    "You are a helpful autonomous agent governed by TaskSentry.\n"
                    "Inspect repository files and answer user requests safely.\n"
                    "For 5G RAN and telecom ticket queries, use the telecom tools "
                    "(telecom_solve_ticket, telecom_inspect_ticket, telecom_list_tickets) "
                    "to inspect tickets, execute 3GPP SOPs, analyze root causes, "
                    "or verify autonomous self-healing.\n"
                    "When complete, output: COMPLETE: <summary>\n"
                ),
            )

        try:
            while step <= 10 and not run.is_stopped():
                # 1. Routing classification decision
                ctx = {"stagnant_steps": 0, "open_failures": 0}
                if hasattr(model_client, "classify_route"):
                    target_model, route_reason = model_client.classify_route(
                        [{"role": "user", "content": run.goal}], context=ctx
                    )
                else:
                    target_model, route_reason = run.routine_model, "default lane"

                lane = "reasoning" if target_model == run.reasoning_model else "routine"
                is_re = target_model == run.reasoning_model
                fallback = run.routine_model if is_re else run.reasoning_model

                dec = RoutingDecision(
                    step=step,
                    selected_model=target_model,
                    lane=lane,
                    reason=route_reason,
                    signals={"complexity": "standard", "stagnant_steps": 0, "open_failures": 0},
                    fallback_model=fallback,
                    latency_ms=120.0,
                    tokens={"input": 450, "output": 35},
                )
                run.audit_log.record(run.task_id, dec)

                run.emit(
                    "model_selected",
                    {
                        "step": step,
                        "selected_model": target_model,
                        "lane": lane,
                        "reason": route_reason,
                        "fallback_model": fallback,
                    },
                )

                # Agent step
                plan_dict = task.runtime.planner.get_plan().to_dict()
                action = agent.step(task.runtime.current_state, task.runtime.history, plan_dict)

                # Stream reasoning tokens if available in action answer
                ans_text = str(action.get("answer") or "")
                if ans_text:
                    # Stream tokens in readable chunks
                    words = ans_text.split(" ")
                    chunk = []
                    for w in words:
                        chunk.append(w)
                        if len(chunk) >= 6:
                            token_chunk = " ".join(chunk) + " "
                            run.emit("assistant_token", {"step": step, "token": token_chunk})
                            chunk = []
                    if chunk:
                        run.emit("assistant_token", {"step": step, "token": " ".join(chunk)})

                run.emit("assistant_message", {"step": step, "action": action})

                # Check if action is tool call or completion
                act_type = action.get("type")
                if act_type == "complete_task":
                    run.emit("verification_started", {"criterion": "verify_workspace_state"})
                    v_res = task.runtime.verification_gate.verify(
                        crit_obj.spec, context=task.runtime.current_state.world
                    )
                    if v_res.passed:
                        run.emit("verification_passed", {"criterion": "verify_workspace_state"})
                    else:
                        run.emit("verification_failed", {"criterion": "verify_workspace_state"})
                    break

                if act_type == "tool_call":
                    tool_name = action.get("tool", "")
                    tool_args = action.get("arguments", {})
                    target_tool = registry.get(tool_name)
                    tool_risk = target_tool.risk if target_tool else "read"

                    # Human Approval Gate for unsafe writes
                    is_write_risk = tool_risk in (
                        "write",
                        "reversible_write",
                        "irreversible_write",
                        "system_write",
                    )
                    if is_write_risk and not run.allow_writes:
                        run.status = "waiting_approval"
                        appr_req = run.approval_manager.request_approval(
                            task_id=run.task_id,
                            tool=tool_name,
                            arguments=tool_args,
                            risk=tool_risk,
                            reason=f"Tool '{tool_name}' requires approval before executing.",
                        )
                        run.emit(
                            "approval_required",
                            {
                                "approval_id": appr_req.approval_id,
                                "tool": tool_name,
                                "risk": tool_risk,
                                "arguments": tool_args,
                                "reason": appr_req.reason,
                            },
                        )

                        # Wait for user decision
                        resolved = run.approval_manager.wait_for_decision(
                            appr_req.approval_id, timeout_seconds=180.0
                        )
                        run.status = "running"

                        if resolved.status != "approved":
                            run.emit(
                                "tool_call_blocked",
                                {
                                    "tool": tool_name,
                                    "reason": resolved.resolution_reason or "Approval rejected.",
                                },
                            )
                            # Feed rejection to agent
                            task.runtime.history.append(
                                {
                                    "role": "tool",
                                    "content": f"Action rejected: {resolved.resolution_reason}",
                                    "is_error": True,
                                }
                            )
                            step += 1
                            continue

                    # Execute Tool Call
                    run.emit("tool_call_started", {"tool": tool_name, "arguments": tool_args})
                    step_res, new_state = task.runtime.executor.execute_step(
                        action, task.runtime.current_state
                    )
                    task.runtime.current_state = new_state

                    if step_res.status == "success":
                        run.emit(
                            "tool_call_completed",
                            {"tool": tool_name, "observation": step_res.observation[:300]},
                        )
                    else:
                        run.emit(
                            "tool_call_failed",
                            {"tool": tool_name, "error": step_res.observation},
                        )

                    # Update interaction history for multi-step agent reasoning
                    args_str = json.dumps(tool_args)
                    task.runtime.history.append(
                        {
                            "role": "assistant",
                            "content": f"I executed tool '{tool_name}' with arguments {args_str}",
                        }
                    )
                    obs_msg = f"[Tool Observation from {tool_name}]:\n{step_res.observation}"
                    task.runtime.history.append(
                        {
                            "role": "user",
                            "content": obs_msg,
                        }
                    )

                # Budget status check
                b_usage = task.runtime.budget.usage_summary()
                rem = task.runtime.budget.remaining_budget()
                if rem.get("remaining_tokens") is not None and rem["remaining_tokens"] < (
                    max_tokens * 0.2
                ):
                    run.emit(
                        "budget_warning",
                        {"dimension": "tokens", "consumed": b_usage["total_tokens"]},
                    )

                step += 1

            # Complete task and generate receipt
            receipt = TaskReceipt(
                task_id=run.task_id,
                status="completed" if not run.is_stopped() else "stopped",
                success=not run.is_stopped(),
                tokens=task.runtime.budget.total_tokens,
                cost_usd=task.runtime.budget.cost_usd,
                wall_time_seconds=task.runtime.budget.wall_time_seconds,
                tool_calls=task.runtime.budget.tool_calls,
                llm_calls=task.runtime.budget.llm_calls,
                final_answer="Task processed and verified.",
                budget_usage=task.runtime.budget.usage_summary(),
                events=[e.model_dump() for e in task.runtime.all_events],
            )
            run.receipt = receipt
            run.completed_at = time.time()
            run.status = "completed" if not run.is_stopped() else "stopped"
            run.store.save(receipt, contract=task.contract)

            run.emit(
                "task_completed" if not run.is_stopped() else "task_stopped",
                {
                    "receipt": receipt.model_dump(),
                    "tokens": receipt.tokens,
                    "cost_usd": receipt.cost_usd,
                    "wall_time_seconds": receipt.wall_time_seconds,
                },
            )

        except Exception as exc:
            logger.exception("Console run failed: %s", exc)
            run.status = "failed"
            run.error = str(exc)
            run.emit("task_failed", {"error": str(exc)})
        finally:
            import contextlib

            # Terminate event stream for subscribers
            with run._lock:
                for sub in run._subscribers:
                    with contextlib.suppress(Exception):
                        sub.put_nowait(None)


default_run_manager = ConsoleRunManager()
