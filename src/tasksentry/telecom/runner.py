"""Batch execution and benchmark evaluation engine for Telecom 5G RAN tickets."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from tasksentry.telecom.agent import TelecomAgent
from tasksentry.telecom.loader import load_tickets
from tasksentry.telecom.models import TelecomResolutionResult, TelecomTicket
from tasksentry.telecom.tools import TelecomSimulationState
from tasksentry.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class TelecomBatchReport:
    """Summary report of a batch telecom troubleshooting run."""

    def __init__(
        self,
        total_tickets: int,
        resolved_count: int,
        escalated_count: int,
        failed_count: int,
        average_compliance_score: float,
        mean_time_to_resolve_seconds: float,
        total_tokens_consumed: int,
        results: list[TelecomResolutionResult],
    ) -> None:
        self.total_tickets = total_tickets
        self.resolved_count = resolved_count
        self.escalated_count = escalated_count
        self.failed_count = failed_count
        self.average_compliance_score = average_compliance_score
        self.mean_time_to_resolve_seconds = mean_time_to_resolve_seconds
        self.total_tokens_consumed = total_tokens_consumed
        self.results = results

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tickets": self.total_tickets,
            "resolved_count": self.resolved_count,
            "escalated_count": self.escalated_count,
            "failed_count": self.failed_count,
            "success_rate": round(self.resolved_count / max(self.total_tickets, 1), 3),
            "average_compliance_score": round(self.average_compliance_score, 3),
            "mean_time_to_resolve_seconds": round(self.mean_time_to_resolve_seconds, 3),
            "total_tokens_consumed": self.total_tokens_consumed,
            "results": [r.model_dump() for r in self.results],
        }


class TelecomBatchRunner:
    """Orchestrates batch execution of tickets from the dataset under TaskSentry governance."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        dataset_path: str = "ran_5g_logs_resolution_sft_chatml_train.jsonl",
        max_tickets: int | None = None,
        brain_model: str = "telco:latest",
        enable_llm_reasoning: bool = False,
        enable_self_healing: bool = True,
    ) -> None:
        self.registry = registry or ToolRegistry()
        self.dataset_path = dataset_path
        self.max_tickets = max_tickets
        self.brain_model = brain_model
        self.enable_llm_reasoning = enable_llm_reasoning
        self.enable_self_healing = enable_self_healing

    def run_ticket(
        self,
        ticket: TelecomTicket,
        sim_state: TelecomSimulationState | None = None,
        enable_llm_reasoning: bool | None = None,
        enable_self_healing: bool | None = None,
    ) -> TelecomResolutionResult:
        """Run a single telecom ticket through the governed agent."""
        state = sim_state or TelecomSimulationState.from_ticket_failure_type(
            ticket.metadata.failure_type
        )
        use_llm = (
            self.enable_llm_reasoning if enable_llm_reasoning is None else enable_llm_reasoning
        )
        use_self_healing = (
            self.enable_self_healing if enable_self_healing is None else enable_self_healing
        )
        agent = TelecomAgent(
            registry=self.registry,
            sim_state=state,
            brain_model=self.brain_model,
            enable_llm_reasoning=use_llm,
            enable_self_healing=use_self_healing,
        )
        return agent.execute_ticket(ticket, enable_self_healing=use_self_healing)

    def run_batch(
        self,
        tickets: list[TelecomTicket] | None = None,
        limit: int | None = None,
        simulate_failures: bool = True,
    ) -> TelecomBatchReport:
        """Run a batch of tickets and calculate SLA and compliance metrics."""
        if tickets is None:
            effective_limit = limit if limit is not None else (self.max_tickets or 10)
            tickets = load_tickets(path=self.dataset_path, limit=effective_limit)

        t0 = time.perf_counter()
        results: list[TelecomResolutionResult] = []
        resolved = 0
        escalated = 0
        failed = 0
        total_compliance = 0.0
        total_tokens = 0

        for t in tickets:
            sim_state = (
                TelecomSimulationState.from_ticket_failure_type(t.metadata.failure_type)
                if simulate_failures
                else None
            )
            res = self.run_ticket(t, sim_state=sim_state)
            results.append(res)

            if res.status == "resolved":
                resolved += 1
            elif res.status == "escalated":
                escalated += 1
            else:
                failed += 1

            total_compliance += res.compliance_score
            total_tokens += res.tokens_consumed

        count = len(tickets)
        avg_comp = total_compliance / max(count, 1)
        total_time = time.perf_counter() - t0
        mttr = total_time / max(count, 1)

        return TelecomBatchReport(
            total_tickets=count,
            resolved_count=resolved,
            escalated_count=escalated,
            failed_count=failed,
            average_compliance_score=avg_comp,
            mean_time_to_resolve_seconds=mttr,
            total_tokens_consumed=total_tokens,
            results=results,
        )

    def save_report(self, report: TelecomBatchReport, output_path: str) -> None:
        """Export report as structured JSON."""
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)

    def run_file(
        self,
        path: str = "ran_5g_logs_resolution_sft_chatml_train.jsonl",
        limit: int = 10,
        output_report_path: str | None = None,
    ) -> TelecomBatchReport:
        """Run tickets loaded from a JSONL file and optionally export a report."""
        tickets = load_tickets(path=path, limit=limit)
        report = self.run_batch(tickets)
        if output_report_path:
            self.save_report(report, output_report_path)
        return report
