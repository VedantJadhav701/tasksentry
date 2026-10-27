"""M1 canonical schema, ingestion, redaction, deduplication, and split tests."""

from __future__ import annotations

import io
import json

import pytest
from pydantic import ValidationError

from tasksentry.domain.ingest import IngestError, ingest, recognize_format
from tasksentry.domain.redact import TenantRedactor
from tasksentry.domain.schema import CommandSpec, Outcome, SopDoc, Step, Ticket, Trajectory
from tasksentry.domain.split import SplitError, split_records


def _record(index: int, *, customer: str | None = None) -> dict[str, object]:
    record: dict[str, object] = {
        "id": f"ticket-{index}",
        "created_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
        "text": f"RAN incident {index}",
    }
    if customer is not None:
        record["customer_id"] = customer
    return record


def test_canonical_trajectory_matches_plan_shape() -> None:
    trajectory = Trajectory(
        tenant_id="acme-telco",
        ticket=Ticket(
            tenant_id="acme-telco",
            id="tsd_000015",
            category="ran_l2/softwarefailure",
            fields={"gnb_id": "8192051"},
            text="cell down",
        ),
        context={"sop_refs": ["sop-ran-017@v3"]},
        steps=[
            Step(
                tenant_id="acme-telco",
                i=1,
                thought_summary="Check DU reachability first.",
                action=CommandSpec(
                    tenant_id="acme-telco", id="du_reachability", args={"mgmt_ip": "<DU_MGMT_IP>"}
                ),
                observation={"status": "ok", "redacted": True},
                posterior={"application_down": 0.27},
            )
        ],
        decision={"root_cause": "application_down_indication_software_crash", "confidence": 0.96},
        remediation={"command_id": "redeploy_action", "risk_tier": "system_write"},
        outcome=Outcome(
            tenant_id="acme-telco",
            resolved=True,
            verification={"method": "sprt", "passed": True},
            label_source="human_confirmed",
        ),
    )
    assert trajectory.schema_version == "1"
    assert trajectory.steps[0].action.id == "du_reachability"


def test_schema_rejects_blank_tenant_and_bad_probability() -> None:
    with pytest.raises(ValidationError):
        Ticket(tenant_id=" ", id="t", text="x")
    with pytest.raises(ValidationError):
        Step(
            tenant_id="tenant",
            i=1,
            action=CommandSpec(tenant_id="tenant", id="probe"),
            posterior={"h": 1.1},
        )


def test_sop_doc_accepts_nested_steps() -> None:
    doc = SopDoc(
        tenant_id="tenant",
        id="sop-1",
        version="v3",
        steps=[
            Step(
                tenant_id="tenant",
                i=1,
                action=CommandSpec(tenant_id="tenant", id="read_link"),
            )
        ],
    )
    assert doc.steps[0].action.id == "read_link"


def test_json_ingestion_and_recognition() -> None:
    result = ingest(json.dumps({"id": "t1", "text": "hello"}))
    assert result.recognition.format == "json"
    assert result.recognition.confidence > 0.9
    assert result.records == [{"id": "t1", "text": "hello"}]


def test_json_array_ingestion() -> None:
    result = ingest(json.dumps([{"id": "t1"}, {"id": "t2"}]))
    assert [row["id"] for row in result.records] == ["t1", "t2"]


def test_jsonl_ingestion_from_file_like() -> None:
    result = ingest(io.StringIO('{"id":"a"}\n{"id":"b"}\n'))
    assert result.recognition.format == "jsonl"
    assert len(result.records) == 2


def test_jsonl_malformed_rows_are_reported_without_losing_valid_rows() -> None:
    result = ingest('{"id":"a"}\nnot-json\n{"id":"b"}', format="jsonl")
    assert [row["id"] for row in result.records] == ["a", "b"]
    assert result.issues[0].row == 2


def test_strict_ingestion_rejects_malformed_rows() -> None:
    with pytest.raises(IngestError):
        ingest('{"id":"a"}\nnot-json', format="jsonl", strict=True)


def test_csv_ingestion() -> None:
    result = ingest("id,text\nt1,cell down\nt2,cell up\n")
    assert result.recognition.format == "csv"
    assert result.records[0] == {"id": "t1", "text": "cell down"}


def test_chatml_ingestion() -> None:
    payload = {"messages": [{"role": "user", "content": "ticket"}]}
    result = ingest(json.dumps(payload))
    assert result.recognition.format == "chatml"
    assert result.records[0]["messages"] == payload["messages"]


def test_optional_recognizer_is_disabled_by_default() -> None:
    class NeverCalled:
        def recognize(self, sample: str):  # type: ignore[no-untyped-def]
            raise AssertionError("optional recognizer was called")

    result = recognize_format("unstructured text", recognizer=NeverCalled())
    assert result.recognizer == "deterministic"


def test_optional_recognizer_can_be_enabled_explicitly() -> None:
    class Recognizer:
        def recognize(self, sample: str):  # type: ignore[no-untyped-def]
            return recognize_format('{"id":"recognized"}')

    result = recognize_format("unstructured text", recognizer=Recognizer(), allow_optional=True)
    assert result.recognizer == "optional"


@pytest.mark.parametrize(
    "text",
    [
        "Contact alice@example.com with token=secret-value-123456789",
        "Bearer sk-abcdefghijklmnopqrstuvwxyz",
        "key='ghp_abcdefghijklmnopqrstuvwxyz'",
        "email bob@example.org and password: hunter2",
    ],
)
def test_redaction_never_returns_known_sensitive_value(text: str) -> None:
    redactor = TenantRedactor("tenant", redact_ips=True)
    output = redactor.redact_text(text)
    assert "@" not in output or "<TS_EMAIL_" in output
    for original in ("alice@example.com", "bob@example.org", "secret-value-123456789", "hunter2"):
        assert original not in output


@pytest.mark.parametrize(
    "value", ["a@example.com", "api_key=sk-abcdefghijklmnopqrstuvwxyz", "10.1.2.3"]
)
def test_redaction_is_idempotent(value: str) -> None:
    redactor = TenantRedactor("tenant", redact_ips=True)
    once = redactor.redact_text(value)
    assert redactor.redact_text(once) == once


def test_redaction_is_reversible_only_with_same_tenant_redactor() -> None:
    owner = TenantRedactor("tenant")
    redacted = owner.redact_text("contact a@example.com")
    assert owner.restore_text(redacted) == "contact a@example.com"
    assert TenantRedactor("other").restore_text(redacted) == redacted


def test_redaction_preserves_nested_record_shape() -> None:
    redactor = TenantRedactor("tenant")
    result = redactor.redact_record({"fields": ["a@example.com", {"note": "safe"}]})
    assert isinstance(result, dict)
    assert result["fields"][1]["note"] == "safe"  # type: ignore[index]
    assert "a@example.com" not in str(result)


def test_duplicate_ids_are_first_wins() -> None:
    result = ingest('[{"id":"same","text":"first"},{"id":"same","text":"second"}]')
    assert result.duplicates_removed == 1
    assert result.records == [{"id": "same", "text": "first"}]


def test_time_split_has_latest_records_in_test() -> None:
    result = split_records([_record(i) for i in range(10)], train_ratio=0.6, val_ratio=0.2)
    assert len(result.train) == 6
    assert len(result.val) == 2
    assert [row["id"] for row in result.test] == ["ticket-8", "ticket-9"]


def test_customer_split_never_leaks_customer_between_partitions() -> None:
    records = [_record(1, customer="a"), _record(2, customer="a"), _record(3, customer="b")]
    result = split_records(records, train_ratio=0.5, val_ratio=0.25)
    locations = {
        customer: {
            name
            for name, rows in (("train", result.train), ("val", result.val), ("test", result.test))
            if any(row.get("customer_id") == customer for row in rows)
        }
        for customer in {"a", "b"}
    }
    assert all(len(partitions) <= 1 for partitions in locations.values())


def test_random_split_is_rejected() -> None:
    with pytest.raises(SplitError, match="time-based"):
        split_records([_record(1)], method="random")


def test_missing_timestamp_is_rejected() -> None:
    with pytest.raises(SplitError, match="timestamp"):
        split_records([{"id": "no-time"}])


def test_split_is_deterministic_and_deduplicates() -> None:
    records = [_record(1), _record(1), _record(2)]
    first = split_records(records, train_ratio=0.5, val_ratio=0.25)
    second = split_records(records, train_ratio=0.5, val_ratio=0.25)
    assert first.model_dump() == second.model_dump()
    assert first.duplicates_removed == 1


def test_split_rejects_invalid_ratios() -> None:
    with pytest.raises(SplitError):
        split_records([_record(1)], train_ratio=0.8, val_ratio=0.3)


def test_redaction_handles_ipv4_and_ipv6_without_touching_other_text() -> None:
    redactor = TenantRedactor("tenant", redact_ips=True)
    result = redactor.redact_text("reach 192.0.2.10 via 2001:db8::1; status ok")
    assert "192.0.2.10" not in result and "2001:db8::1" not in result
    assert result.endswith("status ok")
