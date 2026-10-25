"""Tests for volatile-field normalization and similarity backends."""

import pytest

from tasksentry.math.similarity import (
    EmbeddingSimilarity,
    JaccardSimilarity,
    SimilarityBackend,
    argument_similarity,
    cosine_similarity,
    evidence_novelty,
    jaccard,
    max_similarity,
    normalize_volatile,
    normalized_output_hash,
    tokenize,
)


def test_normalize_removes_timestamps_uuids_and_durations() -> None:
    a = "ok 2026-10-25T10:00:01Z id 123e4567-e89b-12d3-a456-426614174000 took 0.31s"
    b = "ok 2026-11-02T23:59:59Z id 00000000-0000-0000-0000-000000000000 took 12.8s"
    assert normalize_volatile(a) == normalize_volatile(b)
    assert "<timestamp>" in normalize_volatile(a)
    assert "<uuid>" in normalize_volatile(a)
    assert "<duration>" in normalize_volatile(a)


def test_normalize_removes_request_trace_ids_and_tmp_paths() -> None:
    a = "request_id=abc123 trace_id: 9f8e wrote /tmp/pytest-of-user/pytest-1/out.txt"
    b = "request_id=zzz999 trace_id: 1a2b wrote /tmp/pytest-of-other/pytest-77/out.txt"
    assert normalize_volatile(a) == normalize_volatile(b)
    assert "<tmp_path>" in normalize_volatile(a)


def test_normalize_keeps_meaningful_numbers() -> None:
    assert "2 passed" in normalize_volatile("2 passed, 1 failed")
    assert normalize_volatile("2 passed") != normalize_volatile("3 passed")


def test_output_hash_ignores_volatile_but_not_content() -> None:
    assert normalized_output_hash("done in 3s") == normalized_output_hash("done in 9s")
    assert normalized_output_hash("done") != normalized_output_hash("failed")


def test_jaccard_values_and_empty_sets() -> None:
    assert jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == pytest.approx(1 / 3)
    assert jaccard(frozenset(), frozenset()) == 1.0
    assert jaccard(frozenset({"a"}), frozenset()) == 0.0
    assert tokenize("Hello, World hello") == frozenset({"hello", "world"})


def test_default_backend_exact_and_partial_matches() -> None:
    backend = JaccardSimilarity()
    assert isinstance(backend, SimilarityBackend)
    assert backend.similarity("same text", "same   text") == 1.0
    partial = backend.similarity("alpha beta gamma", "alpha beta delta")
    assert partial == pytest.approx(0.5)


def test_evidence_novelty_first_duplicate_and_volatile_only_difference() -> None:
    assert evidence_novelty("first observation", []) == 1.0
    assert evidence_novelty("tests failed: 2", ["tests failed: 2"]) == 0.0
    # Only the duration differs -> not new evidence once volatile fields are normalized.
    assert evidence_novelty("tests failed in 3.2s", ["tests failed in 9.9s"]) == 0.0
    novelty = evidence_novelty("all tests passed", ["tests failed: 2 errors"])
    assert 0.0 < novelty <= 1.0


def test_max_similarity_empty_and_best_match() -> None:
    assert max_similarity("x", []) == 0.0
    best = max_similarity("alpha beta", ["zzz", "alpha beta", "alpha"])
    assert best == 1.0


def test_cosine_similarity_properties_and_errors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 1.0], [-1.0, -1.0]) == pytest.approx(-1.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0
    with pytest.raises(ValueError, match="length"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_embedding_backend_is_pluggable_and_clamps_negative() -> None:
    vectors = {"cat": [1.0, 0.0], "kitten": [0.9, 0.1], "opposite": [-1.0, 0.0]}
    backend = EmbeddingSimilarity(lambda text: vectors[text])
    assert isinstance(backend, SimilarityBackend)
    assert backend.similarity("cat", "kitten") > 0.9
    assert backend.similarity("cat", "opposite") == 0.0
    assert max_similarity("cat", ["kitten"], backend) > 0.9


def test_argument_similarity_detects_near_duplicates_but_not_different_values() -> None:
    near = argument_similarity(
        "search", {"query": "find duplicated pricing logic"},
        "search", {"query": "find duplicated pricing logic"},
    )
    assert near == 1.0
    different_file = argument_similarity(
        "read_file", {"path": "pricing.py"}, "read_file", {"path": "billing.py"}
    )
    assert different_file < 0.92
    assert argument_similarity("a", {"x": 1}, "b", {"x": 1}) == 0.0
    assert argument_similarity("run_tests", {}, "run_tests", {}) == 1.0
