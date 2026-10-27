"""Offline end-to-end 5G domain workflow demo.

Run from the repository root:
``python examples/domain_5g_demo.py --out reports/domain-demo``
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tasksentry.domain.autonomy import AutonomyPolicy, ShadowRecorder, decide_action
from tasksentry.domain.catalog import CommandCatalog, draft_from_sop
from tasksentry.domain.datasets import build_trajectories, export_datasets
from tasksentry.domain.ingest import ingest
from tasksentry.domain.redact import TenantRedactor
from tasksentry.domain.replay import evaluate_replay, write_eval_report
from tasksentry.domain.schema import CommandSpec, Outcome, SopDoc, Step, Ticket
from tasksentry.telecom.loader import load_tickets


def _canonical_sop(tenant_id: str, telecom_sop) -> SopDoc:  # type: ignore[no-untyped-def]
    steps: list[Step] = []
    for telecom_step in telecom_sop.steps:
        command_id = f"ran_sop_step_{telecom_step.step_number}"
        command = CommandSpec(
            tenant_id=tenant_id,
            id=command_id,
            description=telecom_step.title,
            template=("simulated_probe", command_id, "{step}"),
            argument_schema={
                "type": "object",
                "properties": {"step": {"type": "integer", "minimum": 1}},
                "required": ["step"],
            },
            risk_tier="read",
            tenant_scope=tenant_id,
            args={"step": telecom_step.step_number},
        )
        steps.append(
            Step(
                tenant_id=tenant_id,
                i=telecom_step.step_number,
                label_source="auto_verified",
                thought_summary=telecom_step.title,
                action=command,
                observation={
                    "status": "recorded",
                    "simulated": True,
                    "source": "telecom SOP record",
                },
            )
        )
    return SopDoc(
        tenant_id=tenant_id,
        id="sop-ran-demo",
        version="v1",
        title=telecom_sop.problem_category,
        text="Recorded 5G RAN L2 SOP; command execution remains simulated.",
        steps=steps,
    )


def run(output: Path) -> dict[str, object]:
    tenant_id = "demo-telco"
    raw_path = Path(__file__).resolve().parents[1] / "webapp" / "sample_ticket.json"
    ingested = ingest(raw_path)
    redactor = TenantRedactor(tenant_id, redact_ips=True)
    raw = redactor.redact_record(ingested.records[0])
    telecom_ticket = load_tickets(str(raw_path), limit=1)[0]

    ticket = Ticket(
        tenant_id=tenant_id,
        id=str(raw.get("id", telecom_ticket.id)),
        category=telecom_ticket.sop.problem_category,
        fields={"failure_type": telecom_ticket.metadata.failure_type, "source": "simulated"},
        text=str(raw.get("instruction", telecom_ticket.instruction)),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    sop = _canonical_sop(tenant_id, telecom_ticket.sop)
    outcome = Outcome(
        tenant_id=tenant_id,
        label_source="auto_verified",
        resolved=True,
        verification={"method": "simulated_backend", "passed": True, "simulated": True},
    )
    trajectory = build_trajectories([ticket], [sop], {ticket.id: outcome})[0]
    # The demo records the known simulated label and posterior explicitly.
    trajectory = trajectory.model_copy(
        update={
            "decision": {
                "root_cause": telecom_ticket.metadata.failure_type,
                "confidence": 1.0,
                "simulated": True,
            },
            "steps": [
                step.model_copy(update={"posterior": {telecom_ticket.metadata.failure_type: 1.0}})
                for step in trajectory.steps
            ],
        }
    )

    draft = draft_from_sop(sop, version="catalog-demo-v1")
    catalog = CommandCatalog(
        tenant_id=draft.tenant_id,
        version=draft.version,
        commands=draft.commands,
    )
    catalog.validate_links()

    policy = AutonomyPolicy(
        tenant_id=tenant_id,
        levels={"read": "L0", "reversible_write": "L0", "system_write": "L3"},
    )
    shadow = ShadowRecorder()
    for step in trajectory.steps:
        shadow.record(
            decide_action(policy, step.action),
            step.action.args,
            human_action="simulated_observation_only",
        )

    output.mkdir(parents=True, exist_ok=True)
    (output / "trajectory.jsonl").write_text(
        json.dumps(trajectory.model_dump(mode="json"), sort_keys=True) + "\n", encoding="utf-8"
    )
    dataset_report = export_datasets(
        [trajectory],
        output / "dataset",
        catalog_version=catalog.version,
        redaction_stats=redactor.stats.__dict__,
    )
    (output / "shadow.json").write_text(
        json.dumps(
            [
                proposal.decision.model_dump(mode="json") | {"human_action": proposal.human_action}
                for proposal in shadow.proposals()
            ],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    eval_report = evaluate_replay([trajectory], tenant_id=tenant_id, split="test")
    eval_json, eval_markdown = write_eval_report(eval_report, output / "eval")
    return {
        "tenant_id": tenant_id,
        "ticket_id": ticket.id,
        "catalog_commands": len(catalog.commands),
        "dataset_card": str(output / "dataset" / "dataset_card.json"),
        "shadow_proposals": len(shadow.proposals()),
        "eval_json": str(eval_json),
        "eval_markdown": str(eval_markdown),
        "eval_metrics": eval_report.metrics,
        "simulated": True,
        "dataset_trajectories": dataset_report.trajectories,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("reports/domain-demo"))
    args = parser.parse_args()
    print(json.dumps(run(args.out), indent=2, sort_keys=True))
