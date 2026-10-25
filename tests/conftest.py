"""Shared fixtures for the Phase 1 tests."""

from collections.abc import Callable
from typing import Any

import pytest

from tasksentry.core.state import action_fingerprint
from tasksentry.math.progress import ProgressConfig, ProgressTracker, StepScore


@pytest.fixture
def tracker() -> ProgressTracker:
    """A tracker with the documented default configuration."""
    return ProgressTracker(ProgressConfig())


@pytest.fixture
def run_step() -> Callable[..., StepScore]:
    """Return a helper that scores one step on a tracker with sensible defaults.

    The helper computes the action fingerprint from the state hash at call time,
    exactly as the executor will in later phases.
    """

    def _run(
        tracker: ProgressTracker,
        *,
        tool: str = "read_file",
        args: dict[str, Any] | None = None,
        output: str = "file contents",
        before: str = "S0",
        after: str | None = None,
        milestones_before: int = 0,
        milestones_after: int = 0,
        cost: float = 0.0,
        info_gain: float = 0.0,
        **kwargs: Any,
    ) -> StepScore:
        arguments = args if args is not None else {"path": "pricing.py"}
        return tracker.score_step(
            tool_name=tool,
            arguments=arguments,
            output=output,
            fingerprint=action_fingerprint(tool, arguments, before),
            state_hash_before=before,
            state_hash_after=before if after is None else after,
            milestones_before=milestones_before,
            milestones_after=milestones_after,
            cost_usd=cost,
            estimated_information_gain=info_gain,
            **kwargs,
        )

    return _run
