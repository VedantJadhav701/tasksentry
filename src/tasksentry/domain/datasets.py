"""Deterministic training-set exporters derived from canonical trajectories."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.domain.schema import Outcome, SopDoc, Ticket, Trajectory
from tasksentry.domain.split import split_records

VERIFIED_LABELS = frozenset({"human_confirmed", "auto_verified"})


class DatasetExportReport(BaseModel):
    """Machine-readable dataset card and export inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    catalog_version: str
    trajectories: int = Field(ge=0)
    counts: dict[str, int] = Field(default_factory=dict)
    split_counts: dict[str, int] = Field(default_factory=dict)
    label_sources: dict[str, int] = Field(default_factory=dict)
    redaction_stats: dict[str, int] = Field(default_factory=dict)
    data_sha256: str
    files: dict[str, str] = Field(default_factory=dict)


def _sop_map(sops: Mapping[str, SopDoc] | Sequence[SopDoc]) -> dict[str, SopDoc]:
    if isinstance(sops, Mapping):
        return dict(sops)
    return {sop.id: sop for sop in sops}


def _outcome_map(outcomes: Mapping[str, Outcome] | Sequence[Outcome] | None) -> dict[str, Outcome]:
    if outcomes is None:
        return {}
    if isinstance(outcomes, Mapping):
        return dict(outcomes)
    # Outcome has no ticket ID by design; sequence callers should use a mapping.
    raise ValueError("outcomes must be supplied as a mapping keyed by ticket ID")


def build_trajectories(
    tickets: Sequence[Ticket],
    sops: Mapping[str, SopDoc] | Sequence[SopDoc],
    outcomes: Mapping[str, Outcome] | None = None,
) -> list[Trajectory]:
    """Join tickets, SOP steps, and recorded outcomes without inventing observations."""
    sop_by_id = _sop_map(sops)
    outcome_by_id = _outcome_map(outcomes)
    trajectories: list[Trajectory] = []
    for ticket in sorted(tickets, key=lambda item: item.id):
        requested_sop = ticket.fields.get("sop_id")
        sop = sop_by_id.get(str(requested_sop)) if requested_sop else None
        if sop is None:
            sop = next(
                (
                    candidate
                    for candidate in sop_by_id.values()
                    if candidate.tenant_id == ticket.tenant_id
                ),
                None,
            )
        steps = list(sop.steps) if sop is not None else []
        context: dict[str, Any] = {}
        if sop is not None:
            context["sop_refs"] = [f"{sop.id}@{sop.version}"]
        if isinstance(ticket.fields.get("context"), Mapping):
            context.update(dict(ticket.fields["context"]))
        decision = ticket.fields.get("decision")
        remediation = ticket.fields.get("remediation")
        outcome = outcome_by_id.get(ticket.id) or Outcome(
            tenant_id=ticket.tenant_id,
            label_source=ticket.label_source,
            resolved=False,
        )
        trajectories.append(
            Trajectory(
                tenant_id=ticket.tenant_id,
                label_source=outcome.label_source,
                ticket=ticket,
                context=context,
                steps=steps,
                decision=dict(decision) if isinstance(decision, Mapping) else {},
                remediation=dict(remediation) if isinstance(remediation, Mapping) else None,
                outcome=outcome,
            )
        )
    return trajectories


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _label_allowed(label_source: str) -> bool:
    return label_source in VERIFIED_LABELS


def _prompt(trajectory: Trajectory, step_index: int | None = None) -> str:
    payload: dict[str, Any] = {
        "ticket": trajectory.ticket.model_dump(mode="json"),
        "context": trajectory.context,
    }
    if step_index is not None:
        payload["previous_steps"] = [
            step.model_dump(mode="json") for step in trajectory.steps[:step_index]
        ]
    return _canonical(payload)


def _action_record(trajectory: Trajectory, step_index: int) -> dict[str, Any]:
    step = trajectory.steps[step_index]
    action = {"type": "command", "id": step.action.id, "args": step.action.args}
    return {
        "messages": [
            {
                "role": "system",
                "content": "Choose only a typed command from the approved catalog.",
            },
            {"role": "user", "content": _prompt(trajectory, step_index)},
            {"role": "assistant", "content": _canonical(action)},
        ],
        "metadata": {
            "trajectory_id": trajectory.ticket.id,
            "step": step.i,
            "label_source": step.label_source,
        },
    }


def _decision_record(trajectory: Trajectory) -> dict[str, Any] | None:
    if not trajectory.decision or not _label_allowed(trajectory.outcome.label_source):
        return None
    payload: dict[str, Any] = {"type": "decision", **trajectory.decision}
    if trajectory.remediation is not None:
        payload["remediation"] = trajectory.remediation
    return {
        "messages": [
            {"role": "system", "content": "Return a structured diagnosis and decision."},
            {"role": "user", "content": _prompt(trajectory)},
            {"role": "assistant", "content": _canonical(payload)},
        ],
        "metadata": {
            "trajectory_id": trajectory.ticket.id,
            "target": "final_decision",
            "label_source": trajectory.outcome.label_source,
        },
    }


def sft_records(trajectories: Sequence[Trajectory]) -> list[dict[str, Any]]:
    """Create one typed-action example per verified step plus verified decisions."""
    records: list[dict[str, Any]] = []
    for trajectory in sorted(trajectories, key=lambda item: item.ticket.id):
        for index, step in enumerate(trajectory.steps):
            if _label_allowed(step.label_source):
                records.append(_action_record(trajectory, index))
        decision = _decision_record(trajectory)
        if decision is not None:
            records.append(decision)
    return records


def preference_records(trajectories: Sequence[Trajectory]) -> list[dict[str, Any]]:
    """Pair verified-good and verified-bad outcomes within the same ticket category."""
    good: dict[str, list[Trajectory]] = {}
    bad: dict[str, list[Trajectory]] = {}
    for trajectory in trajectories:
        if not _label_allowed(trajectory.outcome.label_source) or not trajectory.decision:
            continue
        bucket = good if trajectory.outcome.resolved else bad
        bucket.setdefault(trajectory.ticket.category, []).append(trajectory)
    pairs: list[dict[str, Any]] = []
    for category in sorted(set(good) & set(bad)):
        winners = sorted(good[category], key=lambda item: item.ticket.id)
        losers = sorted(bad[category], key=lambda item: item.ticket.id)
        for winner, loser in zip(winners, losers, strict=False):
            pairs.append(
                {
                    "prompt": _prompt(winner),
                    "chosen": _canonical(winner.decision),
                    "rejected": _canonical(loser.decision),
                    "metadata": {
                        "category": category,
                        "chosen_id": winner.ticket.id,
                        "rejected_id": loser.ticket.id,
                    },
                }
            )
    return pairs


def refusal_records(trajectories: Sequence[Trajectory]) -> list[dict[str, Any]]:
    """Create escalation examples from verified unresolved outcomes."""
    records: list[dict[str, Any]] = []
    for trajectory in sorted(trajectories, key=lambda item: item.ticket.id):
        if trajectory.outcome.resolved or not _label_allowed(trajectory.outcome.label_source):
            continue
        payload = {"action": "escalate"}
        if trajectory.outcome.escalation_reason:
            payload["reason"] = trajectory.outcome.escalation_reason
        records.append(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": "Escalate when evidence is insufficient or unsafe.",
                    },
                    {"role": "user", "content": _prompt(trajectory)},
                    {"role": "assistant", "content": _canonical(payload)},
                ],
                "metadata": {
                    "trajectory_id": trajectory.ticket.id,
                    "label_source": trajectory.outcome.label_source,
                },
            }
        )
    return records


def format_repair_records(trajectories: Sequence[Trajectory]) -> list[dict[str, Any]]:
    """Export only explicitly recorded malformed/corrected model outputs."""
    records: list[dict[str, Any]] = []
    for trajectory in sorted(trajectories, key=lambda item: item.ticket.id):
        repair = trajectory.context.get("format_repair")
        if not isinstance(repair, Mapping) or "raw" not in repair or "corrected" not in repair:
            continue
        records.append(
            {
                "raw": repair["raw"],
                "corrected": repair["corrected"],
                "metadata": {"trajectory_id": trajectory.ticket.id},
            }
        )
    return records


def _split_trajectories(trajectories: Sequence[Trajectory]) -> dict[str, list[Trajectory]]:
    if not trajectories:
        return {"train": [], "val": [], "test": []}
    records = [
        {
            "id": trajectory.ticket.id,
            "created_at": trajectory.ticket.created_at,
            "customer_id": trajectory.ticket.customer_id,
        }
        for trajectory in trajectories
    ]
    split = split_records(records)
    by_id = {trajectory.ticket.id: trajectory for trajectory in trajectories}
    return {
        name: [by_id[str(row["id"])] for row in rows]
        for name, rows in (("train", split.train), ("val", split.val), ("test", split.test))
    }


def _write_jsonl(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(_canonical(record) + "\n" for record in records),
        encoding="utf-8",
    )


def export_datasets(
    trajectories: Sequence[Trajectory],
    out_dir: str | Path,
    *,
    splits: Mapping[str, Sequence[Trajectory]] | None = None,
    catalog_version: str = "unknown",
    redaction_stats: Mapping[str, int] | None = None,
) -> DatasetExportReport:
    """Write SFT, preference, refusal, repair, and dataset-card artifacts."""
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    split_map = {
        name: list(rows) for name, rows in (splits or _split_trajectories(trajectories)).items()
    }
    all_trajectories = sorted(trajectories, key=lambda item: item.ticket.id)
    source_hash = hashlib.sha256(
        "\n".join(_canonical(item.model_dump(mode="json")) for item in all_trajectories).encode(
            "utf-8"
        )
    ).hexdigest()

    sft = sft_records(all_trajectories)
    preference = preference_records(all_trajectories)
    refusal = refusal_records(all_trajectories)
    repair = format_repair_records(all_trajectories)
    files = {
        "sft": "sft.jsonl",
        "preference": "preference.jsonl",
        "refusal": "refusal.jsonl",
        "format_repair": "format_repair.jsonl",
    }
    records_by_name = {
        "sft": sft,
        "preference": preference,
        "refusal": refusal,
        "format_repair": repair,
    }
    for name, filename in files.items():
        _write_jsonl(output / filename, records_by_name[name])

    label_sources = Counter(item.outcome.label_source for item in all_trajectories)
    counts = {
        "sft": len(sft),
        "preference": len(preference),
        "refusal": len(refusal),
        "format_repair": len(repair),
    }
    report = DatasetExportReport(
        schema_version="1",
        catalog_version=catalog_version,
        trajectories=len(all_trajectories),
        counts=counts,
        split_counts={name: len(rows) for name, rows in sorted(split_map.items())},
        label_sources=dict(sorted(label_sources.items())),
        redaction_stats=dict(sorted((redaction_stats or {}).items())),
        data_sha256=source_hash,
        files=files,
    )
    (output / "dataset_card.json").write_text(
        _canonical(report.model_dump(mode="json")) + "\n", encoding="utf-8"
    )
    markdown = (
        "# TaskSentry Dataset Card\n\n"
        f"- Schema version: `{report.schema_version}`\n"
        f"- Catalog version: `{report.catalog_version}`\n"
        f"- Trajectories: `{report.trajectories}`\n"
        f"- Source SHA-256: `{report.data_sha256}`\n\n"
        "## Counts\n\n"
        + "\n".join(f"- {key}: `{value}`" for key, value in sorted(report.counts.items()))
        + "\n\n## Splits\n\n"
        + "\n".join(f"- {key}: `{value}`" for key, value in sorted(report.split_counts.items()))
        + "\n\n## Label sources\n\n"
        + "\n".join(f"- {key}: `{value}`" for key, value in sorted(report.label_sources.items()))
        + "\n"
    )
    (output / "dataset_card.md").write_text(markdown, encoding="utf-8")
    return report
