"""Unit tests for in-process and process-isolated tool sandboxes."""

import sys
import time

import pytest

from tasksentry.exceptions import IsolationError
from tasksentry.tools.sandbox import Sandbox, SandboxResult


# Module-level functions to ensure picklability in multiprocessing
def sample_add(a: int, b: int) -> int:
    return a + b


def sample_with_output(msg: str) -> str:
    print(f"stdout: {msg}")
    print(f"stderr: {msg}", file=sys.stderr)
    return msg


def sample_raise() -> None:
    raise RuntimeError("simulated tool failure")


def sample_slow(duration: float = 2.0) -> str:
    time.sleep(duration)
    return "done"


def test_in_process_success_and_output_capture() -> None:
    box = Sandbox(mode="in_process")
    res = box.run(sample_with_output, "test_msg")
    assert isinstance(res, SandboxResult)
    assert res.status == "success"
    assert res.result == "test_msg"
    assert "stdout: test_msg" in res.stdout
    assert "stderr: test_msg" in res.stderr
    assert res.error is None
    assert res.duration_ms >= 0.0
    assert res.timed_out is False


def test_in_process_error_capture() -> None:
    box = Sandbox(mode="in_process")
    res = box.run(sample_raise)
    assert res.status == "error"
    assert res.result is None
    assert "RuntimeError" in str(res.error)
    assert "simulated tool failure" in str(res.error)


def test_in_process_mode_label_documentation() -> None:
    """Verify that in-process execution explicitly documents it is NOT a security sandbox."""
    doc = Sandbox._run_in_process.__doc__
    assert doc is not None
    assert "NOT a security sandbox; for deterministic tests only." in doc


def test_process_mode_success() -> None:
    box = Sandbox(mode="process")
    res = box.run(sample_add, 10, 25, timeout_seconds=5.0)
    assert res.status == "success"
    assert res.result == 35
    assert res.timed_out is False


def test_process_mode_error_capture() -> None:
    box = Sandbox(mode="process")
    res = box.run(sample_raise, timeout_seconds=5.0)
    assert res.status == "error"
    assert "RuntimeError" in str(res.error)


def test_process_mode_timeout() -> None:
    box = Sandbox(mode="process")
    res = box.run(sample_slow, 2.0, timeout_seconds=0.2)
    assert res.status == "timeout"
    assert res.timed_out is True
    assert "timed out after 0.2 seconds" in str(res.error)


def test_process_mode_rejects_lambdas_and_closures() -> None:
    box = Sandbox(mode="process")

    # Lambdas are rejected
    with pytest.raises(IsolationError):
        box.run(lambda x: x + 1, 5)

    # Local closures are rejected
    def local_fn(y: int) -> int:
        return y * 2

    with pytest.raises(IsolationError):
        box.run(local_fn, 5)
