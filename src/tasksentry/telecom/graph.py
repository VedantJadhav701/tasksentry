"""Macro-Graph State Machine for Telecom SOP Execution and Failure Routing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from tasksentry.telecom.models import TelecomTicket

logger = logging.getLogger(__name__)


class NodeEvaluationResult(BaseModel):
    """Outcome of executing a single node in the telecom graph."""

    model_config = ConfigDict(extra="ignore")

    status: str  # PASS, FAIL, ESCALATED, RESOLVED
    stdout: str = ""
    subissue: str | None = None
    rca_driver: str | None = None
    escalate_to: str | None = None
    remediation_required: bool = False
    stop: bool = False


class TelecomNode:
    """A single diagnostic, verification, or escalation stage in the telecom SOP graph."""

    def __init__(
        self,
        node_id: str,
        title: str,
        step_number: int | None = None,
        execute_fn: Callable[[dict[str, Any]], NodeEvaluationResult] | None = None,
        is_terminal: bool = False,
    ) -> None:
        self.node_id = node_id
        self.title = title
        self.step_number = step_number
        self.execute_fn = execute_fn
        self.is_terminal = is_terminal
        self.edges: list[TelecomEdge] = []

    def add_edge(self, edge: TelecomEdge) -> None:
        self.edges.append(edge)

    def execute(self, context: dict[str, Any]) -> NodeEvaluationResult:
        if self.execute_fn:
            return self.execute_fn(context)
        return NodeEvaluationResult(status="PASS", stdout=f"Executed node {self.node_id}")


class TelecomEdge:
    """Conditional transition between nodes based on SOP evaluation status."""

    def __init__(
        self,
        target_node_id: str,
        condition_fn: Callable[[NodeEvaluationResult], bool],
        description: str = "",
    ) -> None:
        self.target_node_id = target_node_id
        self.condition_fn = condition_fn
        self.description = description

    def matches(self, result: NodeEvaluationResult) -> bool:
        return self.condition_fn(result)


class TelecomSOPGraph:
    """Deterministic Directed Acyclic Graph (DAG) state machine for 5G RAN tickets."""

    def __init__(self, ticket: TelecomTicket) -> None:
        self.ticket = ticket
        self.nodes: dict[str, TelecomNode] = {}
        self.entry_node_id: str = "node_step_1"
        self._build_graph_from_ticket(ticket)

    def add_node(self, node: TelecomNode) -> None:
        self.nodes[node.node_id] = node

    def _build_graph_from_ticket(self, ticket: TelecomTicket) -> None:
        """Compile ticket SOP steps and next_step_if_failed into graph nodes and edges."""
        steps = ticket.sop.steps

        # 1. Create a node for each step
        for s in steps:
            node_id = f"node_step_{s.step_number}"
            node = TelecomNode(
                node_id=node_id,
                title=s.title,
                step_number=s.step_number,
            )
            self.add_node(node)

        # 2. Add terminal escalation node
        terminal_esc = TelecomNode(
            node_id="node_escalation",
            title="SOP Escalation & Dispatch",
            is_terminal=True,
        )
        self.add_node(terminal_esc)

        # 3. Add terminal resolution node
        terminal_resolve = TelecomNode(
            node_id="node_resolved",
            title="Ticket Verified & Recovered",
            is_terminal=True,
        )
        self.add_node(terminal_resolve)

        # 4. Wire edges based on step expectations and failure rules
        for idx, s in enumerate(steps):
            node_id = f"node_step_{s.step_number}"
            curr_node = self.nodes[node_id]
            is_last = idx == len(steps) - 1
            next_node_id = (
                f"node_step_{steps[idx + 1].step_number}" if not is_last else "node_resolved"
            )

            # Failure edge: if step fails and has stop / escalation
            if s.stop_on_fail or s.escalate_to:
                curr_node.add_edge(
                    TelecomEdge(
                        target_node_id="node_escalation",
                        condition_fn=lambda r: r.status == "FAIL",
                        description=f"Fail -> Escalate to {s.escalate_to or 'Specialist Team'}",
                    )
                )

            # Success edge: if step passes -> advance to next SOP step
            curr_node.add_edge(
                TelecomEdge(
                    target_node_id=next_node_id,
                    condition_fn=lambda r: r.status == "PASS",
                    description="Pass -> Next Step",
                )
            )

            # Default fallback edge
            curr_node.add_edge(
                TelecomEdge(
                    target_node_id=next_node_id,
                    condition_fn=lambda _: True,
                    description="Fallback -> Advance",
                )
            )

    def step_next(self, current_node_id: str, result: NodeEvaluationResult) -> str:
        """Find the next node matching the evaluation condition."""
        node = self.nodes.get(current_node_id)
        if not node or node.is_terminal:
            return ""

        for edge in node.edges:
            if edge.matches(result):
                return edge.target_node_id

        # If no edge matched, default to terminal escalation
        return "node_escalation"
