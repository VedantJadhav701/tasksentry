"""Deterministic replay evaluation over recorded domain trajectories."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.domain.schema import Trajectory


class ReplayError(ValueError):
    """Raised for malformed replay data or an invalid evaluator configuration."""


class ReplayPrediction(BaseModel):
    """Schema for model/plugin output consumed by the evaluator."""

    model_config = ConfigDict(extra="forbid")

    probabilities: dict[str, float] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    escalate: bool = False
    lane: str = "routine"
    tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)


class ReplayBackend:
    """Read-only simulated backend backed by recorded observations."""

    simulated = True

    def __init__(self, trajectory: Trajectory) -> None:
        self.trajectory = trajectory
        self._observations = {step.action.id: dict(step.observation) for step in trajectory.steps}

    def probe(self, command_id: str) -> dict[str, Any]:
        """Return a recorded observation; unknown probes never fabricate output."""
        if command_id not in self._observations:
            raise ReplayError(f"No recorded observation for command {command_id!r}.")
        return dict(self._observations[command_id])


class ReplayModel(Protocol):
    """Plugin protocol for offline model evaluation."""

    def predict(self, trajectory: Trajectory, backend: ReplayBackend) -> Mapping[str, Any]:
        """Return a JSON-like prediction without executing external systems."""


class HarnessOnlyModel:
    """Deterministic no-fine-tune baseline using recorded posterior evidence only."""

    name = "harness-only"

    def predict(self, trajectory: Trajectory, backend: ReplayBackend) -> Mapping[str, Any]:
        del backend
        probabilities: dict[str, float] = {}
        for step in trajectory.steps:
            for hypothesis, probability in step.posterior.items():
                probabilities[hypothesis] = probabilities.get(hypothesis, 0.0) + probability
        if probabilities:
            divisor = sum(probabilities.values()) or 1.0
            probabilities = {key: value / divisor for key, value in probabilities.items()}
        return {
            "probabilities": probabilities,
            "actions": [
                {"id": step.action.id, "args": step.action.args} for step in trajectory.steps
            ],
            "escalate": not trajectory.outcome.resolved,
            "lane": "routine",
            "tokens": 0,
            "latency_ms": 0.0,
        }


class EvalReport(BaseModel):
    """Measured replay report with sample sizes and confidence intervals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluator_version: str = "1"
    tenant_id: str
    split: str
    model_name: str
    samples: int = Field(ge=0)
    metrics: dict[str, float] = Field(default_factory=dict)
    confidence_intervals: dict[str, tuple[float, float]] = Field(default_factory=dict)
    lane_metrics: dict[str, dict[str, float]] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    data_sha256: str
    simulated_backend: bool = True
    errors: list[str] = Field(default_factory=list)


class RegressionDecision(BaseModel):
    """Result of comparing a report with a stored baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    tolerance: float
    regressions: list[str] = Field(default_factory=list)


def _wilson(successes: int, samples: int, confidence: float = 0.95) -> tuple[float, float]:
    if samples <= 0:
        return (0.0, 0.0)
    z = {0.90: 1.6448536269514722, 0.95: 1.959963984540054, 0.99: 2.5758293035489004}.get(
        confidence
    )
    if z is None:
        raise ValueError("confidence must be one of 0.90, 0.95, or 0.99")
    rate = successes / samples
    denominator = 1.0 + z * z / samples
    centre = rate + z * z / (2.0 * samples)
    spread = z * math.sqrt(rate * (1.0 - rate) / samples + z * z / (4.0 * samples * samples))
    return ((centre - spread) / denominator, (centre + spread) / denominator)


def _canonical_hash(trajectories: Sequence[Trajectory]) -> str:
    payload = "\n".join(
        json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for item in sorted(trajectories, key=lambda item: item.ticket.id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prediction(model: Any, trajectory: Trajectory, backend: ReplayBackend) -> ReplayPrediction:
    try:
        raw = (
            model.predict(trajectory, backend)
            if hasattr(model, "predict")
            else model(trajectory, backend)
        )
        return ReplayPrediction.model_validate(raw)
    except Exception as exc:
        raise ReplayError(f"invalid model prediction: {type(exc).__name__}: {exc}") from exc


def evaluate_replay(
    trajectories: Sequence[Trajectory],
    *,
    tenant_id: str,
    split: str = "test",
    model: ReplayModel | Any | None = None,
    model_name: str | None = None,
) -> EvalReport:
    """Evaluate predictions against recorded outcomes with no live backend calls."""
    selected = [item for item in trajectories if item.tenant_id == tenant_id]
    evaluator = model or HarnessOnlyModel()
    resolved_name = str(model_name or getattr(evaluator, "name", type(evaluator).__name__))
    if not selected:
        raise ReplayError(f"No trajectories found for tenant {tenant_id!r}.")

    top1 = top3 = escalation_tp = escalation_fp = escalation_fn = 0
    correct_confidence: list[tuple[float, bool]] = []
    probes: list[float] = []
    unsafe = format_invalid = tool_invalid = tool_attempts = 0
    errors: list[str] = []
    lane_values: dict[str, list[tuple[bool, int, float]]] = defaultdict(list)

    for trajectory in selected:
        backend = ReplayBackend(trajectory)
        try:
            prediction = _prediction(evaluator, trajectory, backend)
        except ReplayError as exc:
            format_invalid += 1
            errors.append(f"{trajectory.ticket.id}: {exc}")
            continue
        probabilities = prediction.probabilities
        ranking = [
            key for key, _ in sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
        ]
        truth = trajectory.decision.get("root_cause")
        correct = bool(truth) and truth == (ranking[0] if ranking else None)
        top1 += int(correct)
        top3 += int(bool(truth) and truth in ranking[:3])
        confidence = probabilities.get(ranking[0], 0.0) if ranking else 0.0
        correct_confidence.append((confidence, correct))

        actual_escalation = not trajectory.outcome.resolved
        if prediction.escalate and actual_escalation:
            escalation_tp += 1
        elif prediction.escalate and not actual_escalation:
            escalation_fp += 1
        elif not prediction.escalate and actual_escalation:
            escalation_fn += 1

        known_ids = {step.action.id for step in trajectory.steps}
        valid_actions = 0
        for action in prediction.actions:
            tool_attempts += 1
            command_id = action.get("id")
            args = action.get("args", {})
            if not isinstance(command_id, str) or not isinstance(args, Mapping):
                tool_invalid += 1
                continue
            if command_id not in known_ids:
                unsafe += 1
                continue
            valid_actions += 1
        probes.append(valid_actions / len(trajectory.steps) if trajectory.steps else 0.0)
        lane_values[prediction.lane].append((correct, prediction.tokens, prediction.latency_ms))

    samples = len(selected)
    valid_predictions = samples - format_invalid
    escalation_precision = (
        escalation_tp / (escalation_tp + escalation_fp) if escalation_tp + escalation_fp else 0.0
    )
    escalation_recall = (
        escalation_tp / (escalation_tp + escalation_fn) if escalation_tp + escalation_fn else 0.0
    )
    ece = 0.0
    for lower in range(0, 10):
        upper = 1.0 if lower == 9 else (lower + 1) / 10
        bucket = [
            (confidence, correct)
            for confidence, correct in correct_confidence
            if lower / 10 <= confidence < upper or (lower == 9 and confidence <= upper)
        ]
        if bucket:
            accuracy = sum(correct for _, correct in bucket) / len(bucket)
            average_confidence = sum(confidence for confidence, _ in bucket) / len(bucket)
            ece += (
                len(bucket) / max(1, len(correct_confidence)) * abs(accuracy - average_confidence)
            )
    format_rate = valid_predictions / samples if samples else 0.0
    tool_rate = 1.0 - tool_invalid / max(1, tool_attempts)
    if tool_attempts == 0:
        tool_rate = 1.0 if tool_invalid == 0 else 0.0
    else:
        tool_rate = max(0.0, 1.0 - tool_invalid / tool_attempts)
    unsafe_rate = unsafe / samples if samples else 0.0
    metrics = {
        "root_cause_top1": top1 / samples if samples else 0.0,
        "root_cause_top3": top3 / samples if samples else 0.0,
        "calibration_ece": ece,
        "probe_efficiency": sum(probes) / len(probes) if probes else 0.0,
        "escalation_precision": escalation_precision,
        "escalation_recall": escalation_recall,
        "unsafe_action_rate": unsafe_rate,
        "format_validity": format_rate,
        "tool_call_validity": tool_rate,
        "cost_per_ticket": 0.0,
        "latency_ms_per_ticket": (
            sum(value[2] for values in lane_values.values() for value in values) / valid_predictions
            if valid_predictions
            else 0.0
        ),
    }
    intervals = {
        "root_cause_top1": _wilson(top1, samples),
        "root_cause_top3": _wilson(top3, samples),
        "format_validity": _wilson(valid_predictions, samples),
        "unsafe_action_rate": _wilson(unsafe, samples),
    }
    lane_metrics = {
        lane: {
            "samples": float(len(values)),
            "top1": sum(correct for correct, _, _ in values) / len(values),
            "tokens_per_ticket": sum(tokens for _, tokens, _ in values) / len(values),
            "latency_ms_per_ticket": sum(latency for _, _, latency in values) / len(values),
        }
        for lane, values in sorted(lane_values.items())
        if values
    }
    return EvalReport(
        tenant_id=tenant_id,
        split=split,
        model_name=resolved_name,
        samples=samples,
        metrics=metrics,
        confidence_intervals=intervals,
        lane_metrics=lane_metrics,
        counts={
            "valid_predictions": valid_predictions,
            "format_invalid": format_invalid,
            "tool_invalid": tool_invalid,
            "unsafe_actions": unsafe,
            "escalation_true_positive": escalation_tp,
            "escalation_false_positive": escalation_fp,
            "escalation_false_negative": escalation_fn,
        },
        data_sha256=_canonical_hash(selected),
        errors=errors,
    )


def compare_baseline(
    current: EvalReport,
    baseline: EvalReport,
    *,
    tolerance: float = 0.02,
) -> RegressionDecision:
    """Fail when quality drops or unsafe/invalid behavior rises beyond tolerance."""
    if tolerance < 0.0:
        raise ValueError("tolerance must be non-negative")
    regressions: list[str] = []
    higher_is_better = (
        "root_cause_top1",
        "root_cause_top3",
        "format_validity",
        "tool_call_validity",
    )
    lower_is_better = ("unsafe_action_rate", "calibration_ece", "latency_ms_per_ticket")
    for metric in higher_is_better:
        if current.metrics.get(metric, 0.0) < baseline.metrics.get(metric, 0.0) - tolerance:
            regressions.append(metric)
    for metric in lower_is_better:
        if current.metrics.get(metric, 0.0) > baseline.metrics.get(metric, 0.0) + tolerance:
            regressions.append(metric)
    return RegressionDecision(passed=not regressions, tolerance=tolerance, regressions=regressions)


def write_eval_report(report: EvalReport, output: str | Path) -> tuple[Path, Path]:
    """Write JSON and Markdown reports and return both paths."""
    target = Path(output)
    if target.suffix.lower() == ".json":
        json_path = target
    else:
        target.mkdir(parents=True, exist_ok=True)
        json_path = target / "replay-eval.json"
    markdown_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# TaskSentry Replay Evaluation",
        "",
        f"- Model: `{report.model_name}`",
        f"- Tenant: `{report.tenant_id}`",
        f"- Split: `{report.split}`",
        f"- Samples: `{report.samples}`",
        f"- Data SHA-256: `{report.data_sha256}`",
        "",
        "## Metrics",
        "",
    ]
    lines.extend(f"- {name}: `{value:.6f}`" for name, value in sorted(report.metrics.items()))
    lines.extend(["", "## Confidence intervals", ""])
    lines.extend(
        f"- {name}: `{interval[0]:.6f}` - `{interval[1]:.6f}`"
        for name, interval in sorted(report.confidence_intervals.items())
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
