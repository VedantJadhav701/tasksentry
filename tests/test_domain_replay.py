"""M5 offline replay evaluator and regression gate tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tasksentry.domain.replay import (
    HarnessOnlyModel,
    ReplayError,
    compare_baseline,
    evaluate_replay,
    write_eval_report,
)
from tasksentry.domain.schema import CommandSpec, Outcome, Step, Ticket, Trajectory


def _trajectory(ticket_id: str, *, resolved: bool = True, day: int = 1) -> Trajectory:
    ticket = Ticket(
        tenant_id="acme",
        id=ticket_id,
        category="ran_l2/softwarefailure",
        text="cell down",
        created_at=datetime(2026, 1, day, tzinfo=UTC),
    )
    step = Step(
        tenant_id="acme",
        i=1,
        action=CommandSpec(tenant_id="acme", id="read_link", args={"host": "du-1"}),
        posterior={"software_crash": 0.9, "fronthaul": 0.1},
        observation={"status": "ok", "stdout": "recorded"},
    )
    return Trajectory(
        tenant_id="acme",
        ticket=ticket,
        steps=[step],
        decision={"root_cause": "software_crash", "confidence": 0.9},
        outcome=Outcome(tenant_id="acme", resolved=resolved),
    )


class GoodModel:
    name = "good-fake"

    def predict(self, trajectory, backend):  # type: ignore[no-untyped-def]
        assert backend.probe("read_link")["status"] == "ok"
        return {
            "probabilities": {"software_crash": 0.9, "fronthaul": 0.1},
            "actions": [{"id": "read_link", "args": {"host": "du-1"}}],
            "escalate": not trajectory.outcome.resolved,
            "lane": "reasoning",
            "tokens": 12,
            "latency_ms": 4.5,
        }


class UnsafeModel:
    def predict(self, trajectory, backend):  # type: ignore[no-untyped-def]
        del trajectory, backend
        return {
            "probabilities": {"software_crash": 1.0},
            "actions": [{"id": "rm_rf", "args": {"path": "/"}}],
            "escalate": False,
        }


def test_harness_baseline_is_deterministic() -> None:
    trajectories = [_trajectory("t1"), _trajectory("t2", day=2)]
    first = evaluate_replay(trajectories, tenant_id="acme", model=HarnessOnlyModel())
    second = evaluate_replay(trajectories, tenant_id="acme", model=HarnessOnlyModel())
    assert first.model_dump() == second.model_dump()


def test_replay_backend_returns_recorded_observation() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    assert report.simulated_backend is True


def test_unknown_probe_does_not_invent_result() -> None:
    from tasksentry.domain.replay import ReplayBackend

    with pytest.raises(ReplayError):
        ReplayBackend(_trajectory("t1")).probe("not_recorded")


def test_good_model_reports_root_cause_and_lane_metrics() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    assert report.metrics["root_cause_top1"] == 1.0
    assert report.lane_metrics["reasoning"]["tokens_per_ticket"] == 12.0


def test_top3_metric_is_reported() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    assert report.metrics["root_cause_top3"] == 1.0


def test_escalation_precision_and_recall() -> None:
    report = evaluate_replay(
        [_trajectory("resolved"), _trajectory("escalated", resolved=False, day=2)],
        tenant_id="acme",
        model=GoodModel(),
    )
    assert report.metrics["escalation_precision"] == 1.0
    assert report.metrics["escalation_recall"] == 1.0


def test_unsafe_fake_model_is_flagged() -> None:
    report = evaluate_replay([_trajectory("unsafe")], tenant_id="acme", model=UnsafeModel())
    assert report.counts["unsafe_actions"] == 1
    assert report.metrics["unsafe_action_rate"] > 0.0


def test_invalid_prediction_is_reported_as_format_failure() -> None:
    def invalid(*args):  # type: ignore[no-untyped-def]
        del args
        return {"probabilities": {"x": "not-a-number"}}

    report = evaluate_replay([_trajectory("invalid")], tenant_id="acme", model=invalid)
    assert report.counts["format_invalid"] == 1
    assert report.metrics["format_validity"] == 0.0


def test_malformed_tool_call_is_invalid() -> None:
    class BadTool:
        def predict(self, trajectory, backend):  # type: ignore[no-untyped-def]
            del trajectory, backend
            return {"actions": [{"id": 4, "args": []}]}

    report = evaluate_replay([_trajectory("bad-tool")], tenant_id="acme", model=BadTool())
    assert report.counts["tool_invalid"] == 1
    assert report.metrics["tool_call_validity"] == 0.0


def test_confidence_intervals_include_sample_sizes() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    assert report.samples == 1
    assert "root_cause_top1" in report.confidence_intervals


def test_ece_is_present_and_bounded() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    assert 0.0 <= report.metrics["calibration_ece"] <= 1.0


def test_report_contains_data_hash_and_writes_json_markdown(tmp_path) -> None:  # type: ignore[no-untyped-def]
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    json_path, markdown_path = write_eval_report(report, tmp_path)
    assert json_path.exists() and markdown_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["data_sha256"] == report.data_sha256


def test_baseline_comparison_passes_equal_report() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    assert compare_baseline(report, report).passed is True


def test_baseline_comparison_flags_quality_regression() -> None:
    report = evaluate_replay([_trajectory("t1")], tenant_id="acme", model=GoodModel())
    degraded = report.model_copy(
        update={
            "metrics": {
                **report.metrics,
                "root_cause_top1": report.metrics["root_cause_top1"] - 0.5,
            }
        }
    )
    decision = compare_baseline(degraded, report, tolerance=0.1)
    assert decision.passed is False and "root_cause_top1" in decision.regressions


def test_tenant_filter_rejects_empty_selection() -> None:
    with pytest.raises(ReplayError):
        evaluate_replay([_trajectory("t1")], tenant_id="other")


def test_replay_does_not_call_network() -> None:
    report = evaluate_replay([_trajectory("offline")], tenant_id="acme")
    assert report.simulated_backend is True and report.model_name == "harness-only"
