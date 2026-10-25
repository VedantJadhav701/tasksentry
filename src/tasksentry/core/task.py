"""Task abstraction managing contracts, runtime instantiation, and agent execution."""

from collections.abc import Sequence
from typing import Any

from tasksentry.budget.budget import Budget
from tasksentry.core.contract import (
    BudgetLimits,
    Milestone,
    SuccessCriterion,
    TaskContract,
    _new_task_id,
)
from tasksentry.core.receipt import TaskReceipt
from tasksentry.core.runtime import CASERuntime
from tasksentry.exceptions import AgentNotFoundError
from tasksentry.harness.agent import Agent, FakeCodingAgent, ScriptedAgent
from tasksentry.harness.verification import VerificationGate
from tasksentry.storage.receipts import ReceiptStore
from tasksentry.tools.registry import ToolRegistry
from tasksentry.tools.sandbox import Sandbox


class AgentTask:
    """Task runner binding a TaskContract to a CASE runtime and executing an AI agent."""

    def __init__(
        self,
        contract: TaskContract | None = None,
        *,
        goal: str | None = None,
        max_llm_calls: int | None = None,
        max_tool_calls: int | None = None,
        max_tokens: int | None = None,
        max_cost_usd: float | None = None,
        max_wall_time_seconds: float | None = None,
        success_criteria: list[SuccessCriterion | dict[str, Any]] | None = None,
        milestones: list[Milestone | dict[str, Any]] | None = None,
        task_id: str | None = None,
        registry: ToolRegistry | None = None,
        budget: Budget | None = None,
        sandbox: Sandbox | None = None,
        verification_gate: VerificationGate | None = None,
        runtime: CASERuntime | None = None,
        agent_registry: Any | None = None,
        store: ReceiptStore | None = None,
    ) -> None:
        if contract is not None:
            self.contract = contract
        else:
            if not goal:
                raise ValueError("Either a TaskContract or a 'goal' must be provided to AgentTask.")
            parsed_criteria: list[SuccessCriterion] = []
            for sc in success_criteria or []:
                if isinstance(sc, SuccessCriterion):
                    parsed_criteria.append(sc)
                elif isinstance(sc, dict):
                    parsed_criteria.append(SuccessCriterion(**sc))

            parsed_milestones: list[Milestone] = []
            for ms in milestones or []:
                if isinstance(ms, Milestone):
                    parsed_milestones.append(ms)
                elif isinstance(ms, dict):
                    parsed_milestones.append(Milestone(**ms))

            b_limits = BudgetLimits(
                max_llm_calls=max_llm_calls,
                max_tool_calls=max_tool_calls,
                max_tokens=max_tokens,
                max_cost_usd=max_cost_usd,
                max_wall_time_seconds=max_wall_time_seconds,
            )
            self.contract = TaskContract(
                task_id=task_id or _new_task_id(),
                goal=goal,
                success_criteria=parsed_criteria,
                milestones=parsed_milestones,
                budget=b_limits,
            )

        # Build Budget if not explicitly provided
        effective_budget = budget
        if effective_budget is None:
            effective_budget = Budget(
                max_llm_calls=self.contract.budget.max_llm_calls,
                max_tool_calls=self.contract.budget.max_tool_calls,
                max_tokens=self.contract.budget.max_tokens,
                max_cost_usd=self.contract.budget.max_cost_usd,
                max_wall_time_seconds=self.contract.budget.max_wall_time_seconds,
            )

        self.runtime = runtime or CASERuntime(
            contract=self.contract,
            registry=registry,
            budget=effective_budget,
            sandbox=sandbox,
            verification_gate=verification_gate,
        )
        self.agent_registry = agent_registry
        self.store = store

    def run(
        self,
        agent: Agent | Sequence[dict[str, Any]] | str = "fake-coding-agent",
        max_steps: int = 50,
    ) -> TaskReceipt:
        """Run task loop using the supplied agent or mock runner."""
        runner: Agent
        if isinstance(agent, str):
            if agent in ("fake-coding-agent", "fake_coding_agent"):
                runner = FakeCodingAgent()
            else:
                from tasksentry.harness.agent import LLMAgent
                from tasksentry.models.fake_model import FakeModel
                from tasksentry.models.registry import AgentRegistry

                target_reg = self.agent_registry
                if target_reg is None:
                    target_reg = AgentRegistry()
                    target_reg.load_from_files()

                try:
                    resolved = target_reg.resolve(agent)
                    if isinstance(resolved.model_client, FakeModel):
                        runner = FakeCodingAgent()
                    else:
                        runner = LLMAgent(
                            model_client=resolved.model_client,
                            registry=self.runtime.registry,
                            system_prompt=resolved.system_prompt or None,
                        )
                except AgentNotFoundError:
                    if target_reg.model_registry.has(agent):
                        client = target_reg.model_registry.get(agent)
                        runner = LLMAgent(
                            model_client=client,
                            registry=self.runtime.registry,
                        )
                    else:
                        raise
                except Exception as exc:
                    raise AgentNotFoundError(f"Unknown named agent '{agent}': {exc}") from exc
        elif isinstance(agent, Agent):
            runner = agent
        else:
            runner = ScriptedAgent(list(agent))

        if hasattr(runner, "budget") and runner.budget is None:
            runner.budget = self.runtime.budget

        receipt = self.runtime.run_loop(runner, max_steps=max_steps)

        if self.store is not None:
            self.store.save(receipt, contract=self.contract)

        return receipt
