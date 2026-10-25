"""Canonical task state and deterministic hashing.

The agent state is ``s_t = (g, M_t, K_t, W_t)``:

* ``g``   - task goal and the machine-checkable success criteria,
* ``M_t`` - completed milestones,
* ``K_t`` - verified facts and artifacts,
* ``W_t`` - external world state relevant to the task.

The *progress-state hash* is computed only from these four parts, after
removing everything volatile. It never includes the remaining budget, the action
history, raw conversation history, timestamps, request IDs, trace IDs, or
ephemeral model-output metadata, because those change on every step and would
make ``StateChange_t`` always equal 1::

    StateChange_t = 1 if hash(s_{t+1}) != hash(s_t) else 0

The *action fingerprint* includes the state hash at call time::

    fingerprint_t = hash(tool_name, canonical_json(arguments), state_hash_at_call)

so ``run_tests()`` before and after an edit are different fingerprints.
"""

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import PurePath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.math.information_gain import ProgressSnapshot
from tasksentry.math.similarity import scrub_volatile

# Keys dropped (case-insensitively) from state values: they are volatile or are
# budget / history / metadata that must never influence the progress hash.
VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "budget",
        "remaining_budget",
        "budget_remaining",
        "history",
        "action_history",
        "conversation",
        "conversation_history",
        "messages",
        "observations",
        "timestamp",
        "timestamps",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "request_id",
        "trace_id",
        "span_id",
        "run_id",
        "duration",
        "duration_ms",
        "latency_ms",
        "elapsed",
        "elapsed_seconds",
        "tokens",
        "cost",
        "cost_usd",
        "usage",
        "model_metadata",
        "model_output_metadata",
        "response_metadata",
    }
)

# Keys whose list values are unordered collections: sorted before hashing.
UNORDERED_KEYS: frozenset[str] = frozenset(
    {
        "open_failures",
        "files_changed",
        "artifacts",
        "passed_checks",
        "milestones_completed",
    }
)


def _sort_key(item: Any) -> str:
    return json.dumps(item, sort_keys=True, default=str, separators=(",", ":"))


def canonicalize(value: Any, *, for_state: bool = True) -> Any:
    """Convert ``value`` into a deterministic JSON-compatible structure.

    Mappings get sorted string keys; sets become sorted lists; floats are rounded
    to 9 decimals; pydantic models are dumped; enums and paths become plain
    strings.

    Args:
        value: any value.
        for_state: if true (state semantics) volatile keys are dropped, volatile
            substrings in strings are replaced by placeholders, and lists under
            :data:`UNORDERED_KEYS` are sorted. If false (argument semantics)
            keys and strings are preserved exactly, so distinct tool arguments
            never collapse into one fingerprint.
    """
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return round(value, 9)
    if isinstance(value, str):
        return _canonical_text(value) if for_state else value
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"), for_state=for_state)
    if isinstance(value, Enum):
        return canonicalize(value.value, for_state=for_state)
    if isinstance(value, PurePath):
        return canonicalize(value.as_posix(), for_state=for_state)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key in value:
            key = str(raw_key)
            lowered = key.lower()
            if for_state and lowered in VOLATILE_KEYS:
                continue
            item = canonicalize(value[raw_key], for_state=for_state)
            if for_state and lowered in UNORDERED_KEYS and isinstance(item, list):
                item = sorted(item, key=_sort_key)
            result[key] = item
        return result
    if isinstance(value, set | frozenset):
        return sorted((canonicalize(v, for_state=for_state) for v in value), key=_sort_key)
    if isinstance(value, list | tuple):
        return [canonicalize(v, for_state=for_state) for v in value]
    text = str(value)
    return _canonical_text(text) if for_state else text


def _canonical_text(text: str) -> str:
    """Scrub volatile substrings and trailing whitespace while keeping layout."""
    scrubbed = scrub_volatile(text)
    return "\n".join(line.rstrip() for line in scrubbed.splitlines()).strip("\n")


def canonical_json(value: Any, *, for_state: bool = True) -> str:
    """Serialize ``canonicalize(value)`` as compact, key-sorted JSON."""
    return json.dumps(
        canonicalize(value, for_state=for_state),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def stable_hash(text: str) -> str:
    """Return the SHA-256 hex digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_state_hash(state: Any) -> str:
    """Hash any state-like value (mapping, model, or :class:`CanonicalState`).

    Volatile keys (budget, history, timestamps, request/trace IDs, ephemeral
    model metadata) are excluded; see :data:`VOLATILE_KEYS`.
    """
    return stable_hash(canonical_json(state, for_state=True))


def action_fingerprint(
    tool_name: str,
    arguments: Mapping[str, Any],
    state_hash_at_call: str,
) -> str:
    """Return ``hash(tool_name, canonical_json(arguments), state_hash_at_call)``."""
    payload = json.dumps(
        {
            "tool": tool_name,
            "args": canonicalize(dict(arguments), for_state=False),
            "state": state_hash_at_call,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return stable_hash(payload)


def normalize_diff(diff: str) -> str:
    """Normalize a git diff for hashing.

    Drops ``index <sha>..<sha>`` lines, scrubs timestamps in file headers, strips
    trailing whitespace, and trims leading/trailing blank lines.
    """
    kept = [line for line in diff.splitlines() if not line.startswith("index ")]
    return _canonical_text("\n".join(kept))


def build_coding_world(
    *,
    git_diff: str = "",
    test_status: str = "unknown",
    open_failures: Iterable[str] = (),
    files_changed: Iterable[str] = (),
    artifacts: Iterable[str] = (),
    passed_checks: int = 0,
) -> dict[str, Any]:
    """Build the canonical ``W_t`` mapping used for coding tasks."""
    return {
        "git_diff_normalized": normalize_diff(git_diff),
        "test_status": test_status,
        "open_failures": sorted(open_failures),
        "files_changed": sorted(files_changed),
        "artifacts": sorted(artifacts),
        "passed_checks": passed_checks,
    }


class CanonicalState(BaseModel):
    """The canonical task state ``s_t = (g, M_t, K_t, W_t)``.

    The model has no field for budget, history, or timestamps, and any such keys
    nested inside ``facts`` or ``world`` are dropped when hashing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str
    criteria_ids: tuple[str, ...] = ()
    milestones: frozenset[str] = frozenset()
    facts: dict[str, Any] = Field(default_factory=dict)
    world: dict[str, Any] = Field(default_factory=dict)

    @property
    def milestone_count(self) -> int:
        """The number of completed milestones ``|M_t|``."""
        return len(self.milestones)

    def canonical_dict(self) -> dict[str, Any]:
        """Return the canonical, hash-ready dictionary form of the state."""
        result: dict[str, Any] = canonicalize(
            {
                "goal": self.goal,
                "criteria": sorted(self.criteria_ids),
                "milestones": sorted(self.milestones),
                "facts": self.facts,
                "world": self.world,
            }
        )
        return result

    def state_hash(self) -> str:
        """Return the progress-state hash of this state."""
        return stable_hash(canonical_json(self.canonical_dict(), for_state=True))

    def with_milestone(self, milestone_id: str) -> "CanonicalState":
        """Return a copy with ``milestone_id`` marked complete."""
        return self.model_copy(update={"milestones": self.milestones | {milestone_id}})

    def with_fact(self, key: str, value: Any) -> "CanonicalState":
        """Return a copy with the verified fact/artifact ``key`` set to ``value``."""
        return self.model_copy(update={"facts": {**self.facts, key: value}})

    def with_world(self, **updates: Any) -> "CanonicalState":
        """Return a copy with ``world`` entries replaced by ``updates``."""
        return self.model_copy(update={"world": {**self.world, **updates}})


def _count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, list | tuple | set | frozenset | dict):
        return len(value)
    return 0


def snapshot_from_state(state: CanonicalState) -> ProgressSnapshot:
    """Extract proxy-estimator counters from a state's ``world`` and milestones."""
    return ProgressSnapshot(
        open_failures=_count(state.world.get("open_failures")),
        passed_checks=_count(state.world.get("passed_checks")),
        completed_milestones=state.milestone_count,
    )
