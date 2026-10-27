"""CLI coverage for the M3 domain workflow."""

from __future__ import annotations

import json

from tasksentry.cli import main
from tasksentry.domain.schema import CommandSpec, Outcome, SopDoc, Step, Ticket, Trajectory


def test_domain_ingest_cli_redacts_and_reports(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "tickets.jsonl"
    source.write_text('{"id":"t1","text":"email a@example.com"}\n', encoding="utf-8")
    out = tmp_path / "ingested"
    assert (
        main(["domain", "ingest", "--input", str(source), "--tenant", "acme", "--out", str(out)])
        == 0
    )
    assert "a@example.com" not in (out / "records.jsonl").read_text(encoding="utf-8")
    assert json.loads((out / "ingest-report.json").read_text(encoding="utf-8"))["records"] == 1
    assert "records" in capsys.readouterr().out


def test_domain_catalog_cli_defaults_to_unapproved_draft(tmp_path) -> None:  # type: ignore[no-untyped-def]
    sop = SopDoc(
        tenant_id="acme",
        id="sop-1",
        version="v1",
        steps=[
            Step(
                tenant_id="acme",
                i=1,
                action=CommandSpec(
                    tenant_id="acme",
                    id="read_link",
                    template=("probe", "{host}"),
                    argument_schema={
                        "properties": {"host": {"type": "string"}},
                        "required": ["host"],
                    },
                ),
            )
        ],
    )
    source = tmp_path / "sop.json"
    source.write_text(json.dumps(sop.model_dump(mode="json")), encoding="utf-8")
    output = tmp_path / "draft.json"
    assert (
        main(
            [
                "domain",
                "catalog",
                "--input",
                str(source),
                "--tenant",
                "acme",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["approved"] is False


def test_domain_export_cli_writes_dataset_card(tmp_path) -> None:  # type: ignore[no-untyped-def]
    trajectory = Trajectory(
        tenant_id="acme",
        ticket=Ticket(
            tenant_id="acme",
            id="t1",
            text="cell down",
            created_at="2026-01-01T00:00:00Z",
        ),
        outcome=Outcome(tenant_id="acme", label_source="human_confirmed"),
    )
    source = tmp_path / "trajectories.jsonl"
    source.write_text(json.dumps(trajectory.model_dump(mode="json")) + "\n", encoding="utf-8")
    output = tmp_path / "export"
    assert (
        main(
            [
                "domain",
                "export",
                "--input",
                str(source),
                "--tenant",
                "acme",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "dataset_card.json").exists()


def test_domain_eval_cli_writes_json_and_markdown(tmp_path) -> None:  # type: ignore[no-untyped-def]
    trajectory = Trajectory(
        tenant_id="acme",
        ticket=Ticket(
            tenant_id="acme",
            id="t1",
            text="cell down",
            created_at="2026-01-01T00:00:00Z",
        ),
        steps=[
            Step(
                tenant_id="acme",
                i=1,
                action=CommandSpec(tenant_id="acme", id="read_link"),
                posterior={"software_crash": 1.0},
                observation={"status": "ok"},
            )
        ],
        decision={"root_cause": "software_crash"},
        outcome=Outcome(tenant_id="acme", resolved=True),
    )
    source = tmp_path / "trajectories.jsonl"
    source.write_text(json.dumps(trajectory.model_dump(mode="json")) + "\n", encoding="utf-8")
    output = tmp_path / "eval"
    assert (
        main(
            [
                "domain",
                "eval",
                "--input",
                str(source),
                "--tenant",
                "acme",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "replay-eval.json").exists()
    assert (output / "replay-eval.md").exists()
