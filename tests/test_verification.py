"""Unit tests for deterministic verifiers and the verification gate."""

import os
import sys

from tasksentry.core.contract import SuccessCriterion, VerifierSpec
from tasksentry.harness.verification import VerificationGate


def test_command_exit_code_verifier() -> None:
    gate = VerificationGate()

    # Successful command (exit 0)
    cmd_ok = [sys.executable, "-c", "import sys; sys.exit(0)"]
    spec_ok = VerifierSpec(verifier="command_exit_code", config={"command": cmd_ok})
    res_ok = gate.verify(spec_ok)
    assert res_ok.passed is True
    assert "exited with 0" in res_ok.message

    # Failing command (exit 2)
    cmd_fail = [sys.executable, "-c", "import sys; sys.exit(2)"]
    spec_fail = VerifierSpec(
        verifier="command_exit_code", config={"command": cmd_fail, "expected_exit_code": 0}
    )
    res_fail = gate.verify(spec_fail)
    assert res_fail.passed is False


def test_command_exit_code_timeout() -> None:
    gate = VerificationGate()
    # Command that sleeps longer than timeout
    cmd = [sys.executable, "-c", "import time; time.sleep(1.0)"]
    spec = VerifierSpec(
        verifier="command_exit_code",
        config={"command": cmd, "timeout_seconds": 0.1},
    )
    res = gate.verify(spec)
    assert res.passed is False
    assert "timed out" in res.message


def test_json_schema_verifier(tmp_path: os.PathLike[str]) -> None:
    gate = VerificationGate()

    # Inline JSON with required keys
    spec = VerifierSpec(
        verifier="json_schema",
        config={
            "data": {"status": "ok", "version": 1},
            "required": ["status", "version"],
        },
    )
    assert gate.verify(spec).passed is True

    # Missing required key
    spec_missing = VerifierSpec(
        verifier="json_schema",
        config={
            "data": {"status": "ok"},
            "required": ["status", "version"],
        },
    )
    res_missing = gate.verify(spec_missing)
    assert res_missing.passed is False
    assert "version" in res_missing.message

    # File-based JSON
    p = os.path.join(tmp_path, "config.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"name": "test_app", "enabled": true}')

    spec_file = VerifierSpec(
        verifier="json_schema",
        config={"file_path": p, "required": ["name"]},
    )
    assert gate.verify(spec_file).passed is True


def test_file_exists_verifier(tmp_path: os.PathLike[str]) -> None:
    gate = VerificationGate()
    file_path = os.path.join(tmp_path, "artifact.txt")

    spec = VerifierSpec(verifier="file_exists", config={"path": file_path})
    assert gate.verify(spec).passed is False

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("hello world")

    assert gate.verify(spec).passed is True

    # Minimum size verification
    spec_size = VerifierSpec(verifier="file_exists", config={"path": file_path, "min_bytes": 100})
    assert gate.verify(spec_size).passed is False


def test_git_diff_nonempty_verifier() -> None:
    gate = VerificationGate()

    # Using context diff
    spec = VerifierSpec(verifier="git_diff_nonempty", config={})
    assert gate.verify(spec, context={"git_diff": "diff --git a/file b/file"}).passed is True
    assert gate.verify(spec, context={"git_diff": ""}).passed is False


def test_regex_match_verifier() -> None:
    gate = VerificationGate()
    spec = VerifierSpec(
        verifier="regex_match",
        config={"pattern": r"Task completed in \d+ms", "text": "Task completed in 42ms"},
    )
    assert gate.verify(spec).passed is True

    spec_fail = VerifierSpec(
        verifier="regex_match",
        config={"pattern": r"^ERROR:", "text": "SUCCESS: All tests passed"},
    )
    assert gate.verify(spec_fail).passed is False


def test_numeric_range_verifier() -> None:
    gate = VerificationGate()

    spec = VerifierSpec(
        verifier="numeric_range",
        config={"key": "accuracy", "min": 0.85, "max": 1.0},
    )
    assert gate.verify(spec, context={"accuracy": 0.92}).passed is True
    assert gate.verify(spec, context={"accuracy": 0.75}).passed is False


def test_python_assert_isolated_subprocess() -> None:
    gate = VerificationGate()

    # Passing assertion
    spec_ok = VerifierSpec(
        verifier="python_assert",
        config={"code": "x = 10 + 5; assert x == 15"},
    )
    res_ok = gate.verify(spec_ok)
    assert res_ok.passed is True
    assert "passed successfully" in res_ok.message

    # Failing assertion
    spec_fail = VerifierSpec(
        verifier="python_assert",
        config={"code": "assert 1 == 2, 'one does not equal two'"},
    )
    res_fail = gate.verify(spec_fail)
    assert res_fail.passed is False
    assert "assertion failed" in res_fail.message


def test_python_assert_timeout() -> None:
    gate = VerificationGate()
    spec = VerifierSpec(
        verifier="python_assert",
        config={"code": "import time; time.sleep(1.0)", "timeout_seconds": 0.1},
    )
    res = gate.verify(spec)
    assert res.passed is False
    assert "timed out" in res.message


def test_artifact_exists_verifier(tmp_path: os.PathLike[str]) -> None:
    gate = VerificationGate()

    # Via context artifacts list
    spec = VerifierSpec(verifier="artifact_exists", config={"artifact_id": "model_weights"})
    assert gate.verify(spec, context={"artifacts": ["model_weights", "summary"]}).passed is True
    assert gate.verify(spec, context={"artifacts": ["other"]}).passed is False


def test_all_required_passed_gate() -> None:
    gate = VerificationGate()

    c1 = SuccessCriterion(
        id="c1",
        verifier="numeric_range",
        config={"value": 10, "min": 0, "max": 20},
        required=True,
    )
    c2 = SuccessCriterion(
        id="c2",
        verifier="numeric_range",
        config={"value": 50, "min": 0, "max": 20},
        required=False,  # Optional
    )

    all_passed, results = gate.all_required_passed([c1, c2])
    assert all_passed is True
    assert len(results) == 2
    assert results[0].passed is True
    assert results[1].passed is False
