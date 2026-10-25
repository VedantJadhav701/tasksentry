"""Tests for canonical state hashing, action fingerprints, and the task contract."""

import pytest
from pydantic import ValidationError

from tasksentry.core.contract import TaskContract
from tasksentry.core.state import (
    CanonicalState,
    action_fingerprint,
    build_coding_world,
    canonical_state_hash,
    normalize_diff,
    snapshot_from_state,
)
from tasksentry.exceptions import ContractError


def _state(**world: object) -> CanonicalState:
    return CanonicalState(goal="fix pricing", criteria_ids=("tests_pass",)).with_world(**world)


# --------------------------------------------------------------------- state hash
def test_hash_ignores_budget_history_and_volatile_keys() -> None:
    base = {"test_status": "failed", "open_failures": ["t1"]}
    noisy = {
        **base,
        "budget": {"remaining_usd": 0.4},
        "remaining_budget": 0.4,
        "history": ["a", "b"],
        "action_history": [1, 2, 3],
        "conversation": "hello",
        "timestamp": "2026-10-25T10:00:00Z",
        "request_id": "req-1",
        "trace_id": "trace-9",
        "model_metadata": {"latency_ms": 123},
    }
    assert canonical_state_hash(base) == canonical_state_hash(noisy)
    other = {**noisy, "budget": {"remaining_usd": 0.1}, "timestamp": "2030-01-01T00:00:00Z"}
    assert canonical_state_hash(noisy) == canonical_state_hash(other)


def test_hash_changes_when_durable_state_changes() -> None:
    assert canonical_state_hash({"test_status": "failed"}) != canonical_state_hash(
        {"test_status": "passed"}
    )


def test_hash_is_independent_of_key_order() -> None:
    a = {"x": 1, "y": {"b": 2, "a": 1}}
    b = {"y": {"a": 1, "b": 2}, "x": 1}
    assert canonical_state_hash(a) == canonical_state_hash(b)


def test_unordered_collections_are_sorted_but_ordered_lists_are_not() -> None:
    assert canonical_state_hash({"open_failures": ["b", "a"]}) == canonical_state_hash(
        {"open_failures": ["a", "b"]}
    )
    assert canonical_state_hash({"steps": ["a", "b"]}) != canonical_state_hash(
        {"steps": ["b", "a"]}
    )


def test_volatile_substrings_inside_values_are_scrubbed() -> None:
    first = {"git_diff_normalized": "ran at 2026-10-25T10:00:00Z in 1.2s"}
    second = {"git_diff_normalized": "ran at 2027-02-02T01:02:03Z in 9.9s"}
    assert canonical_state_hash(first) == canonical_state_hash(second)


def test_canonical_state_hash_changes_with_milestones_facts_and_world() -> None:
    s0 = _state(test_status="failed")
    s1 = s0.with_milestone("locate_bug")
    s2 = s1.with_fact("root_cause", "duplicate discount code")
    s3 = s2.with_world(test_status="passed")
    hashes = {s.state_hash() for s in (s0, s1, s2, s3)}
    assert len(hashes) == 4
    assert s1.milestone_count == 1


def test_state_hash_stable_across_equivalent_construction() -> None:
    a = _state(open_failures=["b", "a"], budget={"usd": 1})
    b = _state(open_failures=["a", "b"], budget={"usd": 0})
    assert a.state_hash() == b.state_hash()
    assert a.state_hash() == canonical_state_hash(a.canonical_dict())


def test_normalize_diff_drops_index_lines_and_timestamps() -> None:
    header = "diff --git a/p.py b/p.py\n"
    diff_a = header + "index 111aaa..222bbb 100644\n--- a/p.py\t2026-10-25 10:00:00\n+x  \n"
    diff_b = header + "index 999fff..888eee 100644\n--- a/p.py\t2027-01-01 00:00:00\n+x\n"
    assert normalize_diff(diff_a) == normalize_diff(diff_b)
    assert "index " not in normalize_diff(diff_a)


def test_build_coding_world_and_snapshot() -> None:
    world = build_coding_world(
        git_diff="+fix",
        test_status="failed",
        open_failures=["test_b", "test_a"],
        files_changed=["pricing.py"],
        artifacts=["analysis/dup.json"],
        passed_checks=3,
    )
    assert world["open_failures"] == ["test_a", "test_b"]
    state = CanonicalState(goal="g", world=world).with_milestone("m1")
    snap = snapshot_from_state(state)
    assert (snap.open_failures, snap.passed_checks, snap.completed_milestones) == (2, 3, 1)


# ---------------------------------------------------------------- action fingerprint
def test_fingerprint_includes_state_so_run_tests_before_and_after_edit_differ() -> None:
    before_edit = canonical_state_hash({"git_diff_normalized": "", "test_status": "failed"})
    after_edit = canonical_state_hash({"git_diff_normalized": "+fix", "test_status": "failed"})
    first = action_fingerprint("run_tests", {}, before_edit)
    second = action_fingerprint("run_tests", {}, after_edit)
    again = action_fingerprint("run_tests", {}, before_edit)
    assert first != second
    assert first == again


def test_fingerprint_is_argument_order_independent_and_argument_sensitive() -> None:
    a = action_fingerprint("search", {"q": "pricing", "limit": 5}, "S")
    b = action_fingerprint("search", {"limit": 5, "q": "pricing"}, "S")
    c = action_fingerprint("search", {"q": "billing", "limit": 5}, "S")
    assert a == b
    assert a != c


def test_fingerprint_keeps_argument_keys_that_state_hashing_would_drop() -> None:
    one = action_fingerprint("lookup", {"request_id": "A"}, "S")
    two = action_fingerprint("lookup", {"request_id": "B"}, "S")
    assert one != two


# ------------------------------------------------------------------------- contract
def _contract(**overrides: object) -> TaskContract:
    data: dict[str, object] = {
        "goal": "Find duplicated pricing logic and make the tests pass.",
        "success_criteria": [
            {"id": "tests_pass", "verifier": "pytest", "config": {"command": "pytest -q"}}
        ],
        "milestones": [
            {
                "id": "locate",
                "done_when": {"verifier": "artifact_exists", "config": {"artifact": "a.json"}},
            },
            {"id": "tests_pass", "done_when": {"verifier": "pytest"}},
        ],
    }
    data.update(overrides)
    return TaskContract.model_validate(data)


def test_contract_accepts_spec_shape_and_builds_initial_state() -> None:
    contract = _contract()
    assert contract.criterion_ids == ("tests_pass",)
    assert contract.milestone_ids == ("locate", "tests_pass")
    state = contract.initial_state()
    assert state.criteria_ids == ("tests_pass",)
    assert state.milestone_count == 0
    assert contract.digest() == _contract(task_id="other-id").digest()
    contract.require_objective_gate()


def test_contract_rejects_plain_string_criteria_and_unknown_verifiers() -> None:
    with pytest.raises(ValidationError):
        _contract(success_criteria=["pytest exits successfully"])
    with pytest.raises(ValidationError, match="unknown verifier"):
        _contract(success_criteria=[{"id": "x", "verifier": "vibes"}])
    with pytest.raises(ValidationError, match="unknown verifier"):
        _contract(milestones=[{"id": "m", "done_when": {"verifier": "llm_says_so"}}])


def test_contract_requires_criteria_unique_ids_and_a_goal() -> None:
    with pytest.raises(ValidationError):
        _contract(success_criteria=[])
    crit = {"id": "dup", "verifier": "file_exists", "config": {"path": "x"}}
    with pytest.raises(ValidationError, match="duplicate success criterion ids"):
        _contract(success_criteria=[crit, crit])
    with pytest.raises(ValidationError):
        _contract(goal="   ")


def test_contract_requires_at_least_one_required_gate() -> None:
    optional = {"id": "x", "verifier": "file_exists", "config": {}, "required": False}
    contract = _contract(success_criteria=[optional])
    with pytest.raises(ContractError):
        contract.require_objective_gate()


def test_contract_budget_validation_and_hypothesis_tracker() -> None:
    with pytest.raises(ValidationError):
        _contract(budget={"max_cost_usd": -1})
    assert _contract().build_belief_tracker() is None
    contract = _contract(
        hypotheses={
            "priors": {"pricing": 0.5, "billing": 0.5},
            "likelihoods": {"fail in pricing": {"pricing": 0.9, "billing": 0.1}},
        }
    )
    tracker = contract.build_belief_tracker()
    assert tracker is not None
    assert tracker.update("fail in pricing").gain_bits > 0.0
    with pytest.raises(ValidationError, match="sum to 1"):
        _contract(hypotheses={"priors": {"a": 0.9, "b": 0.9}})
