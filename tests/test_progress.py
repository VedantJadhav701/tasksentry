"""Tests for APG, rolling window, EMA, the loop policy, and duplicate handling."""

from collections.abc import Callable

import pytest

from tasksentry.math.progress import (
    APGComponents,
    APGWeights,
    LoopAction,
    ProgressConfig,
    ProgressTracker,
    RetryExemptions,
    StepScore,
    compute_apg,
    effective_repetition_penalty,
    ema_update,
    evaluate_loop_policy,
    milestone_progress,
    normalized_cost,
    state_change,
)

RunStep = Callable[..., StepScore]


# ------------------------------------------------------------------ pure formulas
def test_default_weights_match_specification() -> None:
    w = APGWeights()
    assert (w.alpha_1, w.alpha_2, w.alpha_3, w.alpha_4, w.alpha_5, w.alpha_6) == (
        1.0, 1.0, 0.8, 0.8, 2.0, 0.1,
    )


def test_compute_apg_matches_hand_calculation() -> None:
    components = APGComponents(
        state_change=1,
        milestone_progress=2,
        information_gain=0.5,
        evidence_novelty=0.25,
        repetition_penalty=1.0,
        normalized_cost=0.5,
    )
    # 1.0*1 + 1.0*2 + 0.8*0.5 + 0.8*0.25 - 2.0*1.0 - 0.1*0.5 = 1.55
    breakdown = compute_apg(components)
    assert breakdown.apg == pytest.approx(1.55)
    assert breakdown.weighted["repetition_penalty"] == pytest.approx(-2.0)
    custom = compute_apg(components, APGWeights(alpha_1=0.0, alpha_2=0.0, alpha_5=0.0))
    assert custom.apg == pytest.approx(0.4 + 0.2 - 0.05)


def test_state_change_milestone_progress_and_cost_helpers() -> None:
    assert state_change("a", "a") == 0
    assert state_change("a", "b") == 1
    assert milestone_progress(1, 3) == 2
    assert milestone_progress(3, 2) == -1
    assert normalized_cost(0.05, 0.10) == pytest.approx(0.5)
    assert normalized_cost(5.0, 0.10) == 1.0
    assert normalized_cost(-1.0, 0.10) == 0.0
    with pytest.raises(ValueError):
        normalized_cost(1.0, 0.0)


def test_repetition_penalty_cap_and_exemptions() -> None:
    def penalty(*, exact: bool, semantic: bool, exempt: bool) -> float:
        return effective_repetition_penalty(
            exact_repeat=exact, semantic_repeat=semantic, exempt=exempt
        )

    assert penalty(exact=True, semantic=True, exempt=False) == 2.0
    assert penalty(exact=True, semantic=False, exempt=False) == 1.0
    assert penalty(exact=False, semantic=False, exempt=False) == 0.0
    assert penalty(exact=True, semantic=True, exempt=True) == 0.0


def test_ema_update_recursion() -> None:
    ema = 0.0
    values = [1.0, -2.0, 0.5]
    expected = []
    for v in values:
        ema = ema_update(ema, v, 0.3)
        expected.append(ema)
    assert expected[0] == pytest.approx(0.3)
    assert expected[1] == pytest.approx(0.3 * -2.0 + 0.7 * 0.3)
    assert expected[2] == pytest.approx(0.3 * 0.5 + 0.7 * expected[1])


def test_retry_exemptions_union_and_names() -> None:
    a = RetryExemptions(previous_transient_failure=True)
    b = RetryExemptions(new_evidence=True)
    merged = a.merged(b)
    assert merged.any
    assert merged.active == ("previous_transient_failure", "new_evidence")
    assert not RetryExemptions().any


# ----------------------------------------------------------------- loop policy
@pytest.mark.parametrize(
    ("gain", "history", "action", "reason"),
    [
        (-10.0, 4, LoopAction.CONTINUE, "cold_start"),
        (0.01, 5, LoopAction.CONTINUE, "window_gain_positive"),
        (3.0, 9, LoopAction.CONTINUE, "window_gain_positive"),
        (0.0, 5, LoopAction.WARN, "window_gain_zero"),
        (-0.5, 5, LoopAction.WARN, "window_gain_slightly_negative"),
        (-0.999, 5, LoopAction.WARN, "window_gain_slightly_negative"),
        (-1.0, 5, LoopAction.REPLAN, "window_gain_requires_replan"),
        (-1.5, 6, LoopAction.REPLAN, "window_gain_requires_replan"),
        (-1.999, 5, LoopAction.REPLAN, "window_gain_requires_replan"),
        (-2.0, 5, LoopAction.STOP, "window_gain_at_stop_threshold"),
        (-7.5, 8, LoopAction.STOP, "window_gain_at_stop_threshold"),
    ],
)
def test_loop_policy_thresholds(gain: float, history: int, action: LoopAction, reason: str) -> None:
    verdict = evaluate_loop_policy(gain, history, window=5)
    assert (verdict.action, verdict.reason) == (action, reason)
    assert verdict.window_gain == gain


def test_loop_policy_action_values_are_the_canonical_strings() -> None:
    assert {a.value for a in LoopAction} == {
        "continue",
        "warn_and_require_new_approach",
        "force_replan",
        "stop_or_escalate",
    }


# ------------------------------------------------------------- tracker behaviour
def test_first_observation_is_fully_novel(tracker: ProgressTracker, run_step: RunStep) -> None:
    score = run_step(tracker, output="brand new evidence")
    # No state change, no milestones, novelty 1.0, no cost: APG = 0.8
    assert score.apg == pytest.approx(0.8)
    assert not score.exact_repeat
    assert tracker.history_len == 1


def test_productive_run_keeps_continuing(tracker: ProgressTracker, run_step: RunStep) -> None:
    last = None
    for i in range(6):
        last = run_step(
            tracker,
            tool="edit_file",
            args={"path": f"f{i}.py"},
            output=f"edited f{i}.py unique {i}",
            before=f"S{i}",
            after=f"S{i + 1}",
        )
    assert last is not None
    assert last.verdict.action is LoopAction.CONTINUE
    assert last.verdict.reason == "window_gain_positive"
    assert tracker.wasted_steps == 0


def test_exact_repeat_without_exemption_is_penalized_and_loop_stops(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    first = run_step(tracker)
    assert first.apg == pytest.approx(0.8)
    scores = [run_step(tracker) for _ in range(4)]
    for s in scores:
        assert s.exact_repeat
        assert s.semantic_repeat
        assert s.breakdown.components.repetition_penalty == 2.0
        assert s.breakdown.components.evidence_novelty == 0.0
        assert s.apg == pytest.approx(-4.0)
        assert s.is_wasted
    assert scores[-1].verdict.action is LoopAction.STOP
    assert tracker.wasted_steps == 4


def test_cold_start_blocks_stopping_before_window_fills(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    run_step(tracker)
    verdicts = [run_step(tracker).verdict for _ in range(3)]  # steps 2..4
    assert all(v.action is LoopAction.CONTINUE and v.reason == "cold_start" for v in verdicts)


def test_transient_failure_exempts_a_retry(tracker: ProgressTracker, run_step: RunStep) -> None:
    failed = run_step(
        tracker, output="timeout contacting api", is_error=True, is_transient_failure=True
    )
    assert failed.apg > 0  # first attempt, novel
    retry = run_step(tracker, output="timeout contacting api")
    assert retry.exact_repeat
    assert "previous_transient_failure" in retry.exemptions.active
    assert retry.breakdown.components.repetition_penalty == 0.0


def test_previous_error_exempts_a_retry(tracker: ProgressTracker, run_step: RunStep) -> None:
    run_step(tracker, output="bad request: missing field", is_error=True)
    retry = run_step(tracker, output="bad request: missing field")
    assert "previous_observation_error" in retry.exemptions.active
    assert retry.breakdown.components.repetition_penalty == 0.0


def test_changed_durable_state_makes_same_call_productive(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    run_step(tracker, tool="run_tests", args={}, output="2 failed", before="S0")
    rerun = run_step(tracker, tool="run_tests", args={}, output="1 failed", before="S1", after="S1")
    assert not rerun.exact_repeat  # fingerprint includes the state hash
    assert rerun.semantic_repeat
    assert "durable_state_changed" in rerun.exemptions.active
    assert rerun.breakdown.components.repetition_penalty == 0.0


def test_new_evidence_and_milestone_progress_exempt_repeats(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    run_step(tracker, output="first answer about pricing")
    fresh = run_step(tracker, output="a completely different and informative result set")
    assert "new_evidence" in fresh.exemptions.active
    assert fresh.breakdown.components.repetition_penalty == 0.0

    milestone = run_step(
        tracker, output="a completely different and informative result set",
        milestones_before=0, milestones_after=1,
    )
    assert "milestone_progress" in milestone.exemptions.active
    assert milestone.breakdown.components.repetition_penalty == 0.0
    assert milestone.breakdown.components.milestone_progress == 1


def test_caller_supplied_idempotent_exemption(tracker: ProgressTracker, run_step: RunStep) -> None:
    run_step(tracker)
    safe = run_step(tracker, exemptions=RetryExemptions(idempotent_safe=True))
    assert safe.exact_repeat
    assert safe.breakdown.components.repetition_penalty == 0.0
    assert safe.exemptions.active == ("idempotent_safe",)


def test_rolling_window_uses_only_last_n_scores(run_step: RunStep) -> None:
    tracker = ProgressTracker(ProgressConfig(window=5))
    for i in range(8):
        run_step(
            tracker,
            args={"path": f"f{i}"},
            output=f"out {i} unique token{i}",
            before=f"S{i}",
            after=f"S{i + 1}",
        )
    assert tracker.history_len == 8
    assert tracker.window_gain() == pytest.approx(sum(tracker.scores[-5:]))
    assert tracker.window_gain() != pytest.approx(sum(tracker.scores))


def test_tracker_ema_matches_recursion(run_step: RunStep) -> None:
    tracker = ProgressTracker(ProgressConfig(beta=0.3))
    ema = 0.0
    for i in range(4):
        score = run_step(
            tracker,
            args={"path": f"p{i}"},
            output=f"unique output {i}",
            before=f"S{i}",
            after=f"S{i + 1}",
        )
        ema = 0.3 * score.apg + 0.7 * ema
        assert score.ema == pytest.approx(ema)
    assert tracker.ema == pytest.approx(ema)


def test_cost_penalty_is_capped(tracker: ProgressTracker, run_step: RunStep) -> None:
    cheap = run_step(tracker, output="one", args={"path": "a"})
    pricey = run_step(tracker, output="two entirely different words", args={"path": "b"}, cost=50.0)
    assert pricey.breakdown.components.normalized_cost == 1.0
    assert pricey.breakdown.weighted["cost"] == pytest.approx(-0.1)
    assert cheap.breakdown.weighted["cost"] == 0.0


def test_information_gain_term_is_weighted(tracker: ProgressTracker, run_step: RunStep) -> None:
    base = run_step(tracker, output="alpha", args={"path": "a"})
    boosted = run_step(tracker, output="beta gamma", args={"path": "b"}, info_gain=1.0)
    assert boosted.apg - base.apg == pytest.approx(0.8)


# ------------------------------------------------------------ duplicate handling
def test_should_block_only_at_two_prior_occurrences_without_exemption(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    from tasksentry.core.state import action_fingerprint

    fp = action_fingerprint("read_file", {"path": "pricing.py"}, "S0")
    assert not tracker.should_block(fp)
    run_step(tracker)
    assert tracker.fingerprint_count(fp) == 1
    assert not tracker.should_block(fp)
    run_step(tracker)
    assert tracker.fingerprint_count(fp) == 2
    assert tracker.should_block(fp)
    assert not tracker.should_block(fp, RetryExemptions(previous_transient_failure=True))


def test_blocked_duplicates_are_separate_from_window_and_escalate_after_three(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    run_step(tracker)
    window_before = tracker.window_gain()
    steps_before = tracker.history_len
    outcomes = [tracker.register_blocked_duplicate() for _ in range(3)]
    assert [o.penalty for o in outcomes] == [-0.5, -0.5, -0.5]
    assert [o.escalate for o in outcomes] == [False, False, True]
    assert outcomes[-1].blocked_count == 3
    assert outcomes[-1].total_controller_penalty == pytest.approx(-1.5)
    assert tracker.controller_penalty_total == pytest.approx(-1.5)
    assert tracker.window_gain() == window_before  # not part of WindowGain
    assert tracker.history_len == steps_before  # not recorded as an executed action
    assert tracker.decision().action is LoopAction.CONTINUE  # blocks never stop by themselves


def test_blocked_calls_do_not_feed_evidence_novelty(
    tracker: ProgressTracker, run_step: RunStep
) -> None:
    run_step(tracker, output="original observation")
    tracker.register_blocked_duplicate()
    # Novelty is still computed only against executed outputs.
    later = run_step(tracker, args={"path": "other.py"}, output="original observation")
    assert later.breakdown.components.evidence_novelty == 0.0
    different = run_step(tracker, args={"path": "third.py"}, output="something else entirely")
    assert different.breakdown.components.evidence_novelty > 0.5


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        ProgressConfig(window=0)
    with pytest.raises(ValueError):
        ProgressConfig(beta=0.0)
    with pytest.raises(ValueError):
        ProgressConfig(cost_cap=0.0)
