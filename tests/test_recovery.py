"""Unit tests for the RecoveryEngine and context compaction."""

from typing import Any

from tasksentry.harness.recovery import (
    RecoveryAction,
    RecoveryEngine,
    compact_context,
    compute_backoff,
)


def test_compute_backoff_exponential() -> None:
    # Jitter disabled for deterministic calculation check
    d1 = compute_backoff(1, base_delay=1.0, max_delay=10.0, jitter=False)
    d2 = compute_backoff(2, base_delay=1.0, max_delay=10.0, jitter=False)
    d3 = compute_backoff(3, base_delay=1.0, max_delay=10.0, jitter=False)

    assert d1 == 1.0
    assert d2 == 2.0
    assert d3 == 4.0

    # Max delay clamping
    d_max = compute_backoff(10, base_delay=1.0, max_delay=8.0, jitter=False)
    assert d_max == 8.0


def test_transient_error_retry_and_backoff() -> None:
    engine = RecoveryEngine(base_backoff_seconds=0.5)

    dec1 = engine.evaluate_failure(
        tool_name="api_fetch", error_type="503 Unavailable", is_transient=True
    )
    assert dec1.action == RecoveryAction.RETRY
    assert dec1.backoff_seconds > 0.0

    dec2 = engine.evaluate_failure(
        tool_name="api_fetch", error_type="503 Unavailable", is_transient=True
    )
    assert dec2.action == RecoveryAction.RETRY
    assert dec2.details["attempt"] == 2

    # Success resets counters
    engine.record_tool_success("api_fetch")
    dec_after = engine.evaluate_failure(
        tool_name="api_fetch", error_type="503 Unavailable", is_transient=True
    )
    assert dec_after.details["attempt"] == 1


def test_three_consecutive_failures_triggers_replan() -> None:
    engine = RecoveryEngine(max_tool_failures_before_replan=3)

    engine.evaluate_failure(tool_name="build_target", error_type="CompilerError")
    engine.evaluate_failure(tool_name="build_target", error_type="CompilerError")
    dec3 = engine.evaluate_failure(tool_name="build_target", error_type="CompilerError")

    assert dec3.action == RecoveryAction.FORCE_REPLAN
    assert dec3.reason == "repeated_tool_failure"


def test_zero_progress_triggers_replan() -> None:
    engine = RecoveryEngine(max_zero_progress_steps_before_replan=3)

    engine.record_step_progress(apg=-0.1)
    engine.record_step_progress(apg=0.0)
    engine.record_step_progress(apg=-0.5)

    dec = engine.evaluate_failure(tool_name="any_tool", error_type="no_progress")
    assert dec.action == RecoveryAction.FORCE_REPLAN
    assert dec.reason == "zero_progress"


def test_malformed_arguments_schema_correction() -> None:
    engine = RecoveryEngine()
    errs = [{"loc": ["param"], "msg": "value is required"}]
    dec = engine.evaluate_failure(
        tool_name="query",
        error_type="ValidationError",
        is_validation_error=True,
        validation_errors=errs,
    )

    assert dec.action == RecoveryAction.SCHEMA_CORRECTION
    assert dec.details["errors"] == errs


def test_unsafe_write_requires_approval() -> None:
    engine = RecoveryEngine()
    dec = engine.evaluate_failure(
        tool_name="drop_table",
        error_type="UnsafeWrite",
        is_unsafe_write=True,
    )
    assert dec.action == RecoveryAction.PAUSE_APPROVAL
    assert "approval" in dec.message.lower()


def test_context_compaction_and_checkpoint() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "initial instructions"},
        {"role": "assistant", "content": "running tool"},
        {"role": "tool", "content": "error in step 1", "is_error": True},
        {"role": "assistant", "content": "retrying"},
        {"role": "tool", "content": "duplicate output"},
        {"role": "tool", "content": "duplicate output"},
        {"role": "assistant", "content": "latest step done"},
    ]

    compacted, checkpoint = compact_context(
        messages,
        goal="Resolve system latency",
        active_milestone="M1",
        facts={"db_version": "16.1"},
        plan={"current_milestone": "M1"},
        max_retained_history=3,
    )

    assert len(compacted) < len(messages)
    assert compacted[0]["role"] == "system"
    assert "CONTEXT CHECKPOINT" in compacted[0]["content"]
    assert "Resolve system latency" in compacted[0]["content"]

    assert checkpoint["goal"] == "Resolve system latency"
    assert checkpoint["active_milestone"] == "M1"
    assert checkpoint["facts"]["db_version"] == "16.1"
