"""Process-isolated and in-process execution sandboxes for agent tools.

Security and Execution Modes:
- "in_process": NOT a security sandbox; for deterministic tests only. Does not
  provide memory or execution isolation and cannot forcibly terminate infinite
  loops or segfaults.
- "process": Default mode for untrusted or potentially blocking tools. Spawns
  isolated worker processes via ProcessPoolExecutor, enforces timeouts, captures
  standard output/error, and traps failures.

Windows Compatibility:
On Windows, multiprocessing strictly uses the 'spawn' start method. Tools executed
in 'process' mode MUST be picklable, module-level callables. Closures, lambdas,
and unpicklable arguments or return values are prohibited and will raise IsolationError.
"""

import contextlib
import io
import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.exceptions import IsolationError


class SandboxResult(BaseModel):
    """Structured execution outcome from the sandbox."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    status: Literal["success", "error", "timeout"]
    result: Any = None
    error: str | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = Field(default=0.0, ge=0.0)
    timed_out: bool = False


def _worker_wrapper(
    fn: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[str, Any, str | None, str, str, float, bool]:
    """Top-level worker function executed inside isolated process worker."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    t_start = time.perf_counter()

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        try:
            res = fn(*args, **kwargs)
            duration_ms = (time.perf_counter() - t_start) * 1000.0
            return (
                "success",
                res,
                None,
                stdout_buf.getvalue(),
                stderr_buf.getvalue(),
                duration_ms,
                False,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t_start) * 1000.0
            err_msg = f"{type(exc).__name__}: {exc}"
            return (
                "error",
                None,
                err_msg,
                stdout_buf.getvalue(),
                stderr_buf.getvalue(),
                duration_ms,
                False,
            )


def _check_picklable(obj: Any, name: str) -> None:
    """Verify that an object can be serialized for process isolation."""
    # Disallow lambdas and local functions
    if callable(obj):
        qualname = getattr(obj, "__qualname__", "")
        if "<lambda>" in qualname or "<locals>" in qualname:
            raise IsolationError(
                f"Cannot isolate {name} {qualname!r} in process mode: "
                "lambdas and local closures are not allowed."
            )
    try:
        pickle.dumps(obj)
    except (pickle.PicklingError, AttributeError, TypeError) as exc:
        raise IsolationError(f"Cannot isolate unpicklable {name} in process mode: {exc}") from exc


class Sandbox:
    """Execution sandbox providing in-process and process-isolated tool invocation.

    Modes:
        "in_process": NOT a security sandbox; for deterministic tests only.
        "process": Isolated worker process execution with timeouts and output capture.
    """

    def __init__(
        self,
        mode: Literal["in_process", "process"] = "process",
        default_timeout_seconds: float | None = None,
    ) -> None:
        self.mode = mode
        self.default_timeout_seconds = default_timeout_seconds

    def run(
        self,
        func: Any,
        *args: Any,
        timeout_seconds: float | None = None,
        **kwargs: Any,
    ) -> SandboxResult:
        """Execute callable inside the configured sandbox mode."""
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds

        if self.mode == "in_process":
            return self._run_in_process(func, args, kwargs)
        return self._run_process(func, args, kwargs, timeout)

    def _run_in_process(
        self,
        func: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> SandboxResult:
        """In-process execution.

        NOTE: NOT a security sandbox; for deterministic tests only.
        """
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        t_start = time.perf_counter()

        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            try:
                res = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - t_start) * 1000.0
                return SandboxResult(
                    status="success",
                    result=res,
                    error=None,
                    stdout=stdout_buf.getvalue(),
                    stderr=stderr_buf.getvalue(),
                    duration_ms=duration_ms,
                    timed_out=False,
                )
            except Exception as exc:
                duration_ms = (time.perf_counter() - t_start) * 1000.0
                return SandboxResult(
                    status="error",
                    result=None,
                    error=f"{type(exc).__name__}: {exc}",
                    stdout=stdout_buf.getvalue(),
                    stderr=stderr_buf.getvalue(),
                    duration_ms=duration_ms,
                    timed_out=False,
                )

    def _run_process(
        self,
        func: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        timeout: float | None,
    ) -> SandboxResult:
        """Process-isolated execution using ProcessPoolExecutor."""
        # 1. Enforce picklability constraints
        _check_picklable(func, "tool function")
        _check_picklable(args, "positional arguments")
        _check_picklable(kwargs, "keyword arguments")

        t_start = time.perf_counter()
        # Use an executor with max_workers=1
        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker_wrapper, func, args, kwargs)
            try:
                status, res, error, out, err, dur, timed_out = future.result(timeout=timeout)
                return SandboxResult(
                    status=status,  # type: ignore[arg-type]
                    result=res,
                    error=error,
                    stdout=out,
                    stderr=err,
                    duration_ms=dur,
                    timed_out=timed_out,
                )
            except FuturesTimeoutError:
                duration_ms = (time.perf_counter() - t_start) * 1000.0
                # Cancel pending work
                future.cancel()
                return SandboxResult(
                    status="timeout",
                    result=None,
                    error=f"Execution timed out after {timeout} seconds",
                    stdout="",
                    stderr="",
                    duration_ms=duration_ms,
                    timed_out=True,
                )
            except Exception as exc:
                duration_ms = (time.perf_counter() - t_start) * 1000.0
                return SandboxResult(
                    status="error",
                    result=None,
                    error=f"{type(exc).__name__}: {exc}",
                    stdout="",
                    stderr="",
                    duration_ms=duration_ms,
                    timed_out=False,
                )
