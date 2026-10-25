"""The CASE Agent Runtime Loop (Contract -> Planner -> ActionGate -> Executor)."""

from typing import Any

from tasksentry.budget.budget import Budget
from tasksentry.core.contract import TaskContract
from tasksentry.core.events import (
    CHECKPOINT,
    COMPRESS,
    LOOP_DETECTED,
    REPLAN,
    VERIFICATION_FAILED,
    VERIFICATION_PASSED,
    Event,
)
from tasksentry.core.receipt import TaskReceipt
from tasksentry.core.state import CanonicalState
from tasksentry.harness.action_gate import ActionGate
from tasksentry.harness.agent import Agent
from tasksentry.harness.executor import Executor, StepResult
from tasksentry.harness.planner import Planner
from tasksentry.harness.recovery import RecoveryAction, RecoveryEngine, compact_context
from tasksentry.harness.stop_conditions import evaluate_stop_conditions
from tasksentry.harness.verification import VerificationGate, VerificationResult
from tasksentry.math.progress import LoopAction, ProgressTracker
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import ToolRegistry, default_registry
from tasksentry.tools.sandbox import Sandbox


class CASERuntime:
    """The complete CASE execution engine managing the iterative control loop."""

    def __init__(
        self,
        contract: TaskContract,
        *,
        registry: ToolRegistry | None = None,
        budget: Budget | None = None,
        tracker: ProgressTracker | None = None,
        sandbox: Sandbox | None = None,
        verification_gate: VerificationGate | None = None,
    ) -> None:
        self.contract = contract
        self.registry = registry or default_registry
        self.budget = budget or Budget(
            max_llm_calls=contract.budget.max_llm_calls,
            max_tool_calls=contract.budget.max_tool_calls,
            max_tokens=contract.budget.max_tokens,
            max_cost_usd=contract.budget.max_cost_usd,
            max_wall_time_seconds=contract.budget.max_wall_time_seconds,
        )
        self.tracker = tracker or ProgressTracker()
        self.sandbox = sandbox or Sandbox(mode="in_process")
        self.verification_gate = verification_gate or VerificationGate()

        self.governor = ToolGovernor(
            self.registry,
            budget=self.budget,
            tracker=self.tracker,
            sandbox=self.sandbox,
            safety=contract.safety,
        )
        self.planner = Planner(self.contract)
        self.action_gate = ActionGate(
            self.governor,
            self.contract,
            verification_gate=self.verification_gate,
        )
        self.executor = Executor(
            self.governor,
            self.tracker,
            budget=self.budget,
        )
        self.recovery_engine = RecoveryEngine()

        # State ledger
        initial_state = CanonicalState(
            goal=contract.goal,
            criteria_ids=tuple(c.id for c in contract.success_criteria),
            milestones=frozenset(),
        )
        self.current_state = initial_state
        self.state_ledger: list[CanonicalState] = [initial_state]
        self.history: list[dict[str, Any]] = []
        self.step_results: list[StepResult] = []
        self.all_events: list[Event] = []
        self.loop_warnings: int = 0

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> Event:
        event = Event(type=event_type, message=message, data=data or {})
        self.all_events.append(event)
        return event

    def run_loop(self, agent: Agent, max_steps: int = 50) -> TaskReceipt:
        """Run the exact CASE runtime loop until goal satisfaction or termination."""
        final_status = "failed"
        final_answer: str | None = None
        all_criteria_passed = False
        latest_verifications: list[VerificationResult] = []

        for _step_idx in range(1, max_steps + 1):
            # 1. Read current canonical state
            state = self.current_state

            # 2. Ask the model/agent for next action
            plan_dict = self.planner.get_plan().to_dict()
            action = agent.step(state, self.history, plan_dict)

            # 3. Validate and govern action through ActionGate
            context = {"world": state.world, "history": self.history}
            verdict = self.action_gate.evaluate_action(
                action,
                canonical_state=state,
                context=context,
            )

            # Handle completion claim
            if verdict.is_completion_claim:
                if verdict.allowed:
                    # Model claimed completion AND all required verification gates passed!
                    all_criteria_passed = True
                    final_status = "completed"
                    final_answer = (
                        action.get("answer") or "Task completed and verified successfully"
                    )
                    self._emit(VERIFICATION_PASSED, "All verification gates passed", {})
                    break
                else:
                    # Model claimed completion but verification FAILED!
                    self._emit(
                        VERIFICATION_FAILED,
                        verdict.rejection_reason or "Verification failed on completion claim",
                        {},
                    )
                    self.recovery_engine.evaluate_failure(
                        tool_name="complete_task",
                        error_type="verification_failed",
                        is_completion_rejected=True,
                    )
                    self.history.append(
                        {
                            "role": "system",
                            "content": f"Completion rejected: {verdict.rejection_reason}",
                        }
                    )
                    self.planner.replan("Completion rejected by verification gates")
                    continue

            # If action is disallowed or blocked by governor pre-checks
            if not verdict.allowed:
                reason = verdict.rejection_reason or "Action rejected"
                self.history.append({"role": "system", "content": f"Action rejected: {reason}"})
                dec = self.recovery_engine.evaluate_failure(
                    tool_name=action.get("tool", "unknown"),
                    error_type="action_disallowed",
                    blocked_duplicates_count=self.governor.blocked_duplicates_count,
                )
                if dec.action == RecoveryAction.FORCE_REPLAN:
                    self.planner.replan(dec.message)
                elif dec.action == RecoveryAction.ESCALATE:
                    final_status = "escalated"
                    break
                continue

            # 4. Execute through the sandbox and executor
            step_res, new_state = self.executor.execute_step(
                verdict.action_payload,
                state,
                context=context,
            )
            self.step_results.append(step_res)
            self.history.append(
                {
                    "role": "assistant",
                    "content": f"Action: {verdict.action_payload}",
                }
            )
            self.history.append(
                {
                    "role": "tool",
                    "content": step_res.observation,
                    "is_error": (step_res.status != "success"),
                }
            )

            # 5. Run verification checks
            # A) Milestones check
            for m in self.contract.milestones:
                if m.id not in new_state.milestones:
                    v_res = self.verification_gate.verify_milestone(m, context=new_state.world)
                    if v_res.passed:
                        new_state = new_state.with_milestone(m.id)
                        self.planner.update_completed({m.id})

            # B) Success criteria check
            all_passed, verif_results = self.verification_gate.all_required_passed(
                self.contract.success_criteria,
                context=new_state.world,
            )
            latest_verifications = verif_results

            # 6. Update State Ledger
            self.current_state = new_state
            self.state_ledger.append(new_state)

            if all_passed:
                all_criteria_passed = True
                final_status = "completed"
                final_answer = step_res.observation
                self._emit(VERIFICATION_PASSED, "All success criteria verified", {})
                break

            # 7 & 8. Stop / Recovery policy check
            stop_verdict = evaluate_stop_conditions(
                window_gain=step_res.window_gain,
                history_len=self.tracker.history_len,
                window=self.tracker.config.window,
                budget=self.budget,
                all_criteria_passed=all_passed,
                blocked_duplicates_count=self.governor.blocked_duplicates_count,
            )

            if stop_verdict.should_stop:
                if "budget" in stop_verdict.reason or "tool_calls" in stop_verdict.reason:
                    final_status = "stopped"
                elif "three_blocked_duplicates" in stop_verdict.reason:
                    final_status = "escalated"
                elif stop_verdict.action == LoopAction.STOP:
                    final_status = "stopped"
                else:
                    final_status = "completed" if all_passed else "failed"
                break

            if stop_verdict.action == LoopAction.WARN:
                self.loop_warnings += 1
                self._emit(LOOP_DETECTED, f"Anti-loop warning: {stop_verdict.reason}", {})
                self.history.append(
                    {
                        "role": "system",
                        "content": (
                            "Warning: progress gain is zero or slightly negative "
                            f"({stop_verdict.reason}). Try a new approach."
                        ),
                    }
                )

            elif stop_verdict.action == LoopAction.REPLAN:
                self._emit(REPLAN, f"Forced replan: {stop_verdict.reason}", {})
                self.planner.replan(stop_verdict.reason)

            # 9. Context Compaction
            if len(self.history) >= self.recovery_engine.max_context_messages:
                self._emit(COMPRESS, "Context compaction threshold triggered", {})
                compacted, checkpoint = compact_context(
                    self.history,
                    goal=self.contract.goal,
                    active_milestone=self.planner.get_plan().current_milestone,
                    facts=self.current_state.facts,
                    plan=self.planner.get_plan().to_dict(),
                )
                self.history = compacted
                self._emit(CHECKPOINT, "Created context checkpoint", checkpoint)

        # Merge events from all components
        all_events = self.all_events + self.governor.events + self.budget.events
        serial_events = [e.model_dump() for e in all_events]
        serial_verifs = [r.model_dump() for r in latest_verifications]

        slo_met = (
            all_criteria_passed
            and (
                self.contract.budget.max_cost_usd is None
                or self.budget.cost_usd <= self.contract.budget.max_cost_usd
            )
            and (
                self.contract.budget.max_wall_time_seconds is None
                or self.budget.wall_time_seconds <= self.contract.budget.max_wall_time_seconds
            )
        )

        return TaskReceipt(
            task_id=self.contract.task_id,
            status=final_status,
            final_status=final_status,
            success=all_criteria_passed,
            tokens=self.budget.total_tokens,
            cost_usd=round(self.budget.cost_usd, 6),
            llm_calls=self.budget.llm_calls,
            tool_calls=self.budget.tool_calls,
            retries=self.budget.retries,
            wall_time_seconds=round(self.budget.wall_time_seconds, 4),
            duplicate_calls_blocked=self.governor.blocked_duplicates_count,
            controller_penalty=self.governor.controller_penalty_total,
            loop_warnings=self.loop_warnings,
            verification_results=serial_verifs,
            waste_report={
                "wasted_steps": self.tracker.wasted_steps,
                "controller_penalty": self.tracker.controller_penalty_total,
            },
            events=serial_events,
            final_answer=final_answer,
            slo_met=slo_met,
            budget_usage=self.budget.usage_summary(),
        )
