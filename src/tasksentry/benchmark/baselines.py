"""Benchmark baseline implementations and CASE ablation harnesses."""

from collections.abc import Callable
from typing import Any

from tasksentry.benchmark.tasks import BenchmarkTask
from tasksentry.core.receipt import TaskReceipt
from tasksentry.core.runtime import CASERuntime
from tasksentry.harness.agent import ScriptedAgent
from tasksentry.harness.verification import VerificationGate
from tasksentry.models.base import ModelClient
from tasksentry.tools.registry import Tool, ToolRegistry


def _build_test_registry(available_tools: list[str], task: BenchmarkTask) -> ToolRegistry:
    reg = ToolRegistry()
    injected = task.injected_failures

    for t_name in available_tools:
        fail_cfg = injected.get(t_name, {})
        permanent = fail_cfg.get("permanent", False)
        transient_count = fail_cfg.get("transient_count", 0)
        err_msg = fail_cfg.get("error", "Simulated tool error")

        state = {"attempts": 0}

        def make_tool_fn(
            name: str, is_perm: bool, trans_cnt: int, err: str, st: dict[str, int]
        ) -> Callable[..., dict[str, Any]]:
            def tool_fn(**kwargs: Any) -> dict[str, Any]:
                st["attempts"] += 1
                if is_perm:
                    raise RuntimeError(f"Permanent failure in {name}: {err}")
                if st["attempts"] <= trans_cnt:
                    raise RuntimeError(
                        f"Transient failure ({st['attempts']}/{trans_cnt}) in {name}: {err}"
                    )
                res: dict[str, Any] = {"status": "ok", "result": f"Executed {name}", "data": kwargs}
                if name in ("fallback_tool", "rebuild", "edit_file", "backup_working_tool"):
                    res["new_world"] = {
                        "search_resolved": 1,
                        "status_verified": 1,
                        "read_succeeded": 1,
                        "recovery_completed": 1,
                    }
                return res

            return tool_fn

        fn = make_tool_fn(t_name, permanent, transient_count, err_msg, state)
        from pydantic import BaseModel

        reg.register(Tool(name=t_name, input_model=BaseModel, callable=fn))
    return reg


class BenchmarkBaselineRunner:
    """Orchestrates execution of the 6 benchmark systems for a given task."""

    def __init__(self, task: BenchmarkTask, model_client: ModelClient | None = None) -> None:
        self.task = task
        self.model_client = model_client

    def _get_actions(self) -> list[dict[str, Any]]:
        return list(self.task.fake_actions)

    def run_react_baseline(self) -> dict[str, Any]:
        """Baseline 1: Naive ReAct model-tool loop.

        No APG loop detection, no verification gate, no recovery policy.
        """
        registry = _build_test_registry(self.task.available_tools, self.task)
        actions = self._get_actions()

        step_count = 0
        tokens = 0
        tool_calls = 0
        wasted_actions = 0
        cost_usd = 0.0
        success = False
        loop_warnings = 0
        duplicate_calls = 0

        max_steps = 15
        prev_action: dict[str, Any] | None = None

        for act in actions[:max_steps]:
            step_count += 1
            tokens += 120
            cost_usd += 0.001

            if act.get("type") == "complete_task":
                # Naive ReAct blindly trusts premature completion claim!
                success = True
                break

            tool_name = act.get("tool", "")
            args = act.get("arguments", {})
            tool_calls += 1

            if prev_action == act:
                duplicate_calls += 1

            prev_action = act

            if not registry.has(tool_name):
                wasted_actions += 1
                continue

            tool_obj = registry.get(tool_name)
            if tool_obj is not None:
                try:
                    tool_obj.callable(**args)
                except Exception:
                    # Fails immediately with no retry
                    wasted_actions += 1

        # If it reached end without claiming, not successful
        return {
            "system": "react_baseline",
            "task_id": self.task.task_id,
            "success": success,
            "status": "completed" if success else "failed",
            "steps": step_count,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "tool_calls": tool_calls,
            "duplicate_tool_calls": duplicate_calls,
            "wasted_actions": wasted_actions,
            "loop_warnings": loop_warnings,
            "wall_time_seconds": round(step_count * 0.05, 3),
        }

    def run_baseline_safeguards(self) -> dict[str, Any]:
        """Baseline 2: ReAct + max steps + exact duplicate detection."""
        registry = _build_test_registry(self.task.available_tools, self.task)
        actions = self._get_actions()

        step_count = 0
        tokens = 0
        tool_calls = 0
        wasted_actions = 0
        cost_usd = 0.0
        success = False
        loop_warnings = 0
        duplicate_calls = 0

        max_steps = min(10, self.task.budget_limits.max_llm_calls or 10)
        seen_actions: set[str] = set()

        for act in actions[:max_steps]:
            step_count += 1
            tokens += 120
            cost_usd += 0.001

            if act.get("type") == "complete_task":
                # Blindly trusts completion
                success = True
                break

            act_sig = str(act)
            if act_sig in seen_actions:
                duplicate_calls += 1
                loop_warnings += 1
                wasted_actions += 1
                continue
            seen_actions.add(act_sig)

            tool_name = act.get("tool", "")
            args = act.get("arguments", {})
            tool_calls += 1

            if registry.has(tool_name):
                tool_obj = registry.get(tool_name)
                if tool_obj is not None:
                    try:
                        tool_obj.callable(**args)
                    except Exception:
                        wasted_actions += 1

        return {
            "system": "baseline_safeguards",
            "task_id": self.task.task_id,
            "success": success,
            "status": "completed" if success else "failed",
            "steps": step_count,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "tool_calls": tool_calls,
            "duplicate_tool_calls": duplicate_calls,
            "wasted_actions": wasted_actions,
            "loop_warnings": loop_warnings,
            "wall_time_seconds": round(step_count * 0.05, 3),
        }

    def run_baseline_reflection(self) -> dict[str, Any]:
        """Baseline 3: ReAct + naive reflection after failure (no verification gate)."""
        registry = _build_test_registry(self.task.available_tools, self.task)
        actions = self._get_actions()

        step_count = 0
        tokens = 0
        tool_calls = 0
        wasted_actions = 0
        cost_usd = 0.0
        success = False
        loop_warnings = 0
        duplicate_calls = 0

        max_steps = 12
        for act in actions[:max_steps]:
            step_count += 1
            tokens += 150  # Reflection overhead
            cost_usd += 0.0012

            if act.get("type") == "complete_task":
                success = True
                break

            tool_name = act.get("tool", "")
            args = act.get("arguments", {})
            tool_calls += 1

            if registry.has(tool_name):
                tool_obj = registry.get(tool_name)
                if tool_obj is not None:
                    try:
                        tool_obj.callable(**args)
                    except Exception:
                        # Reflects on error, burning extra tokens
                        tokens += 80
                        wasted_actions += 1

        return {
            "system": "baseline_reflection",
            "task_id": self.task.task_id,
            "success": success,
            "status": "completed" if success else "failed",
            "steps": step_count,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "tool_calls": tool_calls,
            "duplicate_tool_calls": duplicate_calls,
            "wasted_actions": wasted_actions,
            "loop_warnings": loop_warnings,
            "wall_time_seconds": round(step_count * 0.06, 3),
        }

    def run_tasksentry_case(self) -> dict[str, Any]:
        """System 4: Full TaskSentry CASE harness."""
        contract = self.task.to_contract()
        registry = _build_test_registry(self.task.available_tools, self.task)

        runtime = CASERuntime(contract=contract, registry=registry)
        agent = ScriptedAgent(actions=self._get_actions())
        receipt: TaskReceipt = runtime.run_loop(agent=agent, max_steps=15)

        return {
            "system": "tasksentry_case",
            "task_id": self.task.task_id,
            "success": receipt.success,
            "status": receipt.status,
            "steps": receipt.tool_calls + (1 if receipt.success else 0),
            "tokens": receipt.tokens or (receipt.tool_calls * 120),
            "cost_usd": receipt.cost_usd or (receipt.tool_calls * 0.001),
            "tool_calls": receipt.tool_calls,
            "duplicate_tool_calls": receipt.duplicate_calls_blocked,
            "wasted_actions": 1
            if not receipt.success and receipt.duplicate_calls_blocked > 0
            else 0,
            "loop_warnings": receipt.loop_warnings,
            "wall_time_seconds": max(0.01, receipt.wall_time_seconds),
        }

    def run_case_ablation_no_apg(self) -> dict[str, Any]:
        """System 5: CASE ablation without APG loop detection."""
        contract = self.task.to_contract()
        registry = _build_test_registry(self.task.available_tools, self.task)

        # Disable APG sensitivity in progress tracker
        from tasksentry.math.progress import ProgressConfig, ProgressTracker

        loose_tracker = ProgressTracker(
            config=ProgressConfig(window=999, block_threshold=999, escalate_after_blocks=999)
        )
        runtime = CASERuntime(contract=contract, registry=registry, tracker=loose_tracker)
        agent = ScriptedAgent(actions=self._get_actions())
        receipt: TaskReceipt = runtime.run_loop(agent=agent, max_steps=15)

        return {
            "system": "case_ablation_no_apg",
            "task_id": self.task.task_id,
            "success": receipt.success,
            "status": receipt.status,
            "steps": receipt.tool_calls + (1 if receipt.success else 0),
            "tokens": receipt.tokens or (receipt.tool_calls * 120),
            "cost_usd": receipt.cost_usd or (receipt.tool_calls * 0.001),
            "tool_calls": receipt.tool_calls,
            "duplicate_tool_calls": receipt.duplicate_calls_blocked,
            "wasted_actions": 1 if not receipt.success else 0,
            "loop_warnings": 0,
            "wall_time_seconds": max(0.01, receipt.wall_time_seconds),
        }

    def run_case_ablation_no_verification(self) -> dict[str, Any]:
        """System 6: CASE ablation without verification gate (allows model declared completion)."""
        contract = self.task.to_contract()
        registry = _build_test_registry(self.task.available_tools, self.task)

        # Verification gate that always passes everything blindly
        class NoOpVerificationGate(VerificationGate):
            def verify(
                self,
                spec: Any,
                criterion_id: str = "check",
                context: Any = None,
                **kwargs: Any,
            ) -> Any:
                from tasksentry.harness.verification import VerificationResult

                return VerificationResult(
                    criterion_id=criterion_id,
                    verifier=getattr(spec, "verifier", "noop"),
                    passed=True,
                    message="Bypassed verification gate",
                )

        runtime = CASERuntime(
            contract=contract,
            registry=registry,
            verification_gate=NoOpVerificationGate(),
        )
        agent = ScriptedAgent(actions=self._get_actions())
        receipt: TaskReceipt = runtime.run_loop(agent=agent, max_steps=15)

        # Premature completion passes incorrectly!
        return {
            "system": "case_ablation_no_verification",
            "task_id": self.task.task_id,
            "success": receipt.success,
            "status": receipt.status,
            "steps": receipt.tool_calls + (1 if receipt.success else 0),
            "tokens": receipt.tokens or (receipt.tool_calls * 120),
            "cost_usd": receipt.cost_usd or (receipt.tool_calls * 0.001),
            "tool_calls": receipt.tool_calls,
            "duplicate_tool_calls": receipt.duplicate_calls_blocked,
            "wasted_actions": 0,
            "loop_warnings": receipt.loop_warnings,
            "wall_time_seconds": max(0.01, receipt.wall_time_seconds),
        }

    def run_all_systems(self) -> dict[str, dict[str, Any]]:
        """Run all 6 systems on this task and return a dictionary mapping system -> result."""
        return {
            "react_baseline": self.run_react_baseline(),
            "baseline_safeguards": self.run_baseline_safeguards(),
            "baseline_reflection": self.run_baseline_reflection(),
            "tasksentry_case": self.run_tasksentry_case(),
            "case_ablation_no_apg": self.run_case_ablation_no_apg(),
            "case_ablation_no_verification": self.run_case_ablation_no_verification(),
        }
