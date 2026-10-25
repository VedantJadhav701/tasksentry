"""Task abstraction managing contracts, runtime instantiation, and agent execution."""

from collections.abc import Sequence
from typing import Any

from tasksentry.budget.budget import Budget
from tasksentry.core.contract import TaskContract
from tasksentry.core.receipt import TaskReceipt
from tasksentry.core.runtime import CASERuntime
from tasksentry.harness.agent import Agent, FakeCodingAgent, ScriptedAgent
from tasksentry.harness.verification import VerificationGate
from tasksentry.tools.registry import ToolRegistry
from tasksentry.tools.sandbox import Sandbox


class AgentTask:
    """Task runner binding a TaskContract to a CASE runtime and executing an AI agent."""

    def __init__(
        self,
        contract: TaskContract,
        *,
        registry: ToolRegistry | None = None,
        budget: Budget | None = None,
        sandbox: Sandbox | None = None,
        verification_gate: VerificationGate | None = None,
        runtime: CASERuntime | None = None,
    ) -> None:
        self.contract = contract
        self.runtime = runtime or CASERuntime(
            contract=contract,
            registry=registry,
            budget=budget,
            sandbox=sandbox,
            verification_gate=verification_gate,
        )

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
                raise ValueError(f"Unknown named agent {agent!r}")
        elif isinstance(agent, Agent):
            runner = agent
        else:
            runner = ScriptedAgent(list(agent))

        return self.runtime.run_loop(runner, max_steps=max_steps)
