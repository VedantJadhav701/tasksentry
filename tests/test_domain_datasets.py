"""M3 deterministic dataset exporter tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from tasksentry.domain.datasets import (
    build_trajectories,
    export_datasets,
    format_repair_records,
    preference_records,
    refusal_records,
    sft_records,
)
from tasksentry.domain.schema import CommandSpec, Outcome, SopDoc, Step, Ticket, Trajectory


def _command(command_id: str = "read_link") -> CommandSpec:
    return CommandSpec(
        tenant_id="acme",
        id=command_id,
        args={"host": "du-1"},
        template=("probe", "{host}"),
        argument_schema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": ["host"],
        },
    )


def _trajectory(
    ticket_id: str,
    *,
    label: str = "human_confirmed",
    resolved: bool = True,
    day: int = 1,
    customer: str = "customer-a",
    repair: bool = False,
) -> Trajectory:
    context: dict[str, object] = {"sop_refs": ["sop-1@v1"]}
    if repair:
        context["format_repair"] = {"raw": "{bad", "corrected": '{"action":"escalate"}'}
    ticket = Ticket(
        tenant_id="acme",
        id=ticket_id,
        category="softwarefailure",
        fields={"decision": {"root_cause": "software_crash", "confidence": 0.9}},
        text="cell is down",
        customer_id=customer,
        created_at=datetime(2026, 1, day, tzinfo=UTC),
    )
    step = Step(
        tenant_id="acme",
        i=1,
        label_source=label,  # type: ignore[arg-type]
        thought_summary="Read the link state.",
        action=_command(),
        observation={"status": "ok"},
    )
    return Trajectory(
        tenant_id="acme",
        ticket=ticket,
        context=context,
        steps=[step],
        decision=ticket.fields["decision"],  # type: ignore[arg-type]
        remediation={"command_id": "restart_link"},
        outcome=Outcome(
            tenant_id="acme",
            label_source=label,  # type: ignore[arg-type]
            resolved=resolved,
            verification={"passed": resolved},
            escalation_reason=None if resolved else "evidence insufficient",
        ),
    )


def test_build_trajectories_joins_ticket_sop_and_outcome() -> None:
    ticket = Ticket(
        tenant_id="acme",
        id="t1",
        category="ran",
        fields={"sop_id": "sop-1"},
        text="cell down",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    sop = SopDoc(
        tenant_id="acme",
        id="sop-1",
        version="v1",
        steps=[Step(tenant_id="acme", i=1, action=_command())],
    )
    outcome = Outcome(tenant_id="acme", resolved=True, label_source="auto_verified")
    result = build_trajectories([ticket], [sop], {"t1": outcome})
    assert result[0].steps[0].action.id == "read_link"
    assert result[0].outcome.resolved is True
    assert result[0].context["sop_refs"] == ["sop-1@v1"]


def test_build_does_not_invent_observations() -> None:
    ticket = Ticket(
        tenant_id="acme",
        id="t1",
        text="cell down",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    result = build_trajectories([ticket], [])
    assert result[0].steps == []
    assert result[0].outcome.resolved is False


def test_sft_has_one_action_example_per_verified_step() -> None:
    records = sft_records([_trajectory("t1")])
    assert len(records) == 2
    action = json.loads(records[0]["messages"][-1]["content"])
    assert action == {"args": {"host": "du-1"}, "id": "read_link", "type": "command"}


def test_sft_final_decision_contains_remediation() -> None:
    records = sft_records([_trajectory("t1")])
    decision = json.loads(records[-1]["messages"][-1]["content"])
    assert decision["type"] == "decision"
    assert decision["remediation"]["command_id"] == "restart_link"


def test_inferred_decision_is_not_exported() -> None:
    assert sft_records([_trajectory("t1", label="inferred")]) == []


def test_auto_verified_decision_is_exported() -> None:
    records = sft_records([_trajectory("t1", label="auto_verified")])
    assert len(records) == 2


def test_preference_pairs_match_same_category() -> None:
    pairs = preference_records([_trajectory("good"), _trajectory("bad", resolved=False, day=2)])
    assert len(pairs) == 1
    assert pairs[0]["metadata"]["chosen_id"] == "good"
    assert pairs[0]["metadata"]["rejected_id"] == "bad"


def test_preference_does_not_pair_different_categories() -> None:
    good = _trajectory("good")
    bad = _trajectory("bad", resolved=False)
    bad = bad.model_copy(update={"ticket": bad.ticket.model_copy(update={"category": "other"})})
    assert preference_records([good, bad]) == []


def test_refusal_set_contains_only_verified_escalations() -> None:
    records = refusal_records([_trajectory("bad", resolved=False)])
    assert len(records) == 1
    assert json.loads(records[0]["messages"][-1]["content"])["action"] == "escalate"
    assert refusal_records([_trajectory("inferred", label="inferred", resolved=False)]) == []


def test_format_repair_requires_explicit_pair() -> None:
    records = format_repair_records([_trajectory("repair", repair=True)])
    assert records == [
        {
            "raw": "{bad",
            "corrected": '{"action":"escalate"}',
            "metadata": {"trajectory_id": "repair"},
        }
    ]
    assert format_repair_records([_trajectory("none")]) == []


def test_export_writes_all_artifacts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = export_datasets([_trajectory("t1", repair=True)], tmp_path)
    assert report.trajectories == 1
    for filename in (
        "sft.jsonl",
        "preference.jsonl",
        "refusal.jsonl",
        "format_repair.jsonl",
        "dataset_card.json",
        "dataset_card.md",
    ):
        assert (tmp_path / filename).exists()


def test_export_is_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    first = export_datasets([_trajectory("t1")], tmp_path / "one")
    second = export_datasets([_trajectory("t1")], tmp_path / "two")
    assert first.model_dump() == second.model_dump()
    assert (tmp_path / "one" / "sft.jsonl").read_bytes() == (
        tmp_path / "two" / "sft.jsonl"
    ).read_bytes()


def test_export_reports_label_sources_and_redaction_stats(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = export_datasets(
        [_trajectory("t1"), _trajectory("t2", label="auto_verified")],
        tmp_path,
        redaction_stats={"emails": 2},
        catalog_version="catalog-v3",
    )
    assert report.catalog_version == "catalog-v3"
    assert report.label_sources == {"auto_verified": 1, "human_confirmed": 1}
    assert report.redaction_stats == {"emails": 2}


def test_explicit_split_counts_are_preserved(tmp_path) -> None:  # type: ignore[no-untyped-def]
    train = _trajectory("train")
    test = _trajectory("test", day=2)
    report = export_datasets(
        [train, test], tmp_path, splits={"train": [train], "val": [], "test": [test]}
    )
    assert report.split_counts == {"test": 1, "train": 1, "val": 0}


def test_every_sft_line_is_json_chat_schema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    export_datasets([_trajectory("t1")], tmp_path)
    lines = (tmp_path / "sft.jsonl").read_text(encoding="utf-8").splitlines()
    for line in lines:
        value = json.loads(line)
        assert [message["role"] for message in value["messages"]] == [
            "system",
            "user",
            "assistant",
        ]
