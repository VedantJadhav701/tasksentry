"""Similarity primitives used for evidence novelty and repetition detection.

Everything here is deterministic and offline. The default backend combines:

1. an exact hash of the *normalized* text (volatile fields removed), and
2. token-set Jaccard similarity.

An optional embedding backend (cosine similarity) can be plugged in through the
:class:`SimilarityBackend` protocol.

Equations
---------
Jaccard similarity of token sets ``A`` and ``B``::

    J(A, B) = |A intersect B| / |A union B|        (J = 1 when both are empty)

Cosine similarity of vectors ``u`` and ``v``::

    cos(u, v) = (u . v) / (||u|| * ||v||)          (0 when either norm is 0)

Evidence novelty (used by Agent Progress Gain)::

    EvidenceNovelty_t = 1 - max_j sim(o_t, o_j)    over recent normalized outputs o_j
"""

import hashlib
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

_UUID = r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
_ISO_TIMESTAMP = r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
_CLOCK_TIME = r"\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b"
_REQUEST_ID = r"(?i)\b(?:request|req)[_-]?id\b\s*[=:]\s*(?:<[a-z_]+>|[\w.\-]+)"
_TRACE_ID = r"(?i)\b(?:trace|span)[_-]?id\b\s*[=:]\s*(?:<[a-z_]+>|[\w.\-]+)"
_POSIX_TMP = r"(?:/private)?(?:/tmp|/var/folders|/var/tmp)/[^\s'\"]*"
_WINDOWS_TMP = r"[A-Za-z]:\\[^\s'\"]*\\Temp\\[^\s'\"]*"
_EPOCH = r"\b1\d{9}(?:\d{3})?\b"
_DURATION = r"\b\d+(?:\.\d+)?\s?(?:ms|us|ns|s|secs?|seconds?|mins?|minutes?)\b"

_VOLATILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(_UUID), "<uuid>"),
    (re.compile(_ISO_TIMESTAMP), "<timestamp>"),
    (re.compile(_CLOCK_TIME), "<time>"),
    (re.compile(_REQUEST_ID), "request_id=<id>"),
    (re.compile(_TRACE_ID), "trace_id=<id>"),
    (re.compile(_POSIX_TMP), "<tmp_path>"),
    (re.compile(_WINDOWS_TMP), "<tmp_path>"),
    (re.compile(_EPOCH), "<epoch>"),
    (re.compile(_DURATION), "<duration>"),
)
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9_]+")


def scrub_volatile(text: str) -> str:
    """Replace volatile substrings with stable placeholders, keeping whitespace.

    Volatile fields are timestamps, clock times, UUIDs, request/trace/span IDs,
    durations, epoch values, and temporary paths. Layout (newlines, indentation)
    is preserved so that structured text such as diffs stays meaningful.
    """
    for pattern, replacement in _VOLATILE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def normalize_volatile(text: str) -> str:
    """Scrub volatile fields and collapse all whitespace runs to single spaces."""
    return _WHITESPACE.sub(" ", scrub_volatile(text)).strip()


def normalized_output_hash(text: str) -> str:
    """Return the SHA-256 hex digest of the volatile-normalized text."""
    return hashlib.sha256(normalize_volatile(text).encode("utf-8")).hexdigest()


def tokenize(text: str) -> frozenset[str]:
    """Return the lowercase token set of volatile-normalized text."""
    return frozenset(_TOKEN.findall(normalize_volatile(text).lower()))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-set Jaccard similarity ``|A & B| / |A | B|`` (1.0 for two empty sets)."""
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either has zero norm.

    Raises:
        ValueError: if the vectors differ in length.
    """
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


@runtime_checkable
class SimilarityBackend(Protocol):
    """Protocol for pluggable text-similarity implementations.

    Implementations return a value in ``[0, 1]`` where 1 means identical.
    """

    def similarity(self, a: str, b: str) -> float:
        """Return the similarity of two texts in ``[0, 1]``."""
        ...


class JaccardSimilarity:
    """Default backend: exact normalized-hash match, then token-set Jaccard."""

    def similarity(self, a: str, b: str) -> float:
        """Return 1.0 for identical normalized texts, else the token Jaccard score."""
        if normalized_output_hash(a) == normalized_output_hash(b):
            return 1.0
        return jaccard(tokenize(a), tokenize(b))


class EmbeddingSimilarity:
    """Optional backend: cosine similarity of caller-supplied embeddings.

    Args:
        embed: function mapping text to a fixed-length vector. Any embedding
            model can be used; none is bundled so the core stays offline.

    Negative cosine values are clamped to 0 so the result stays in ``[0, 1]``.
    """

    def __init__(self, embed: Callable[[str], Sequence[float]]) -> None:
        self._embed = embed
        self._cache: dict[str, Sequence[float]] = {}

    def _vector(self, text: str) -> Sequence[float]:
        key = normalize_volatile(text)
        if key not in self._cache:
            self._cache[key] = self._embed(key)
        return self._cache[key]

    def similarity(self, a: str, b: str) -> float:
        """Return clamped cosine similarity of the two embedded texts."""
        return max(0.0, cosine_similarity(self._vector(a), self._vector(b)))


def max_similarity(
    candidate: str,
    recent: Iterable[str],
    backend: SimilarityBackend | None = None,
) -> float:
    """Return ``max_j sim(candidate, recent_j)`` in ``[0, 1]`` (0.0 if ``recent`` is empty)."""
    chosen = backend or JaccardSimilarity()
    best = 0.0
    for prior in recent:
        best = max(best, chosen.similarity(candidate, prior))
    return max(0.0, min(1.0, best))


def evidence_novelty(
    output: str,
    recent_outputs: Iterable[str],
    backend: SimilarityBackend | None = None,
) -> float:
    """Compute ``EvidenceNovelty = 1 - max_similarity(output, recent_outputs)``.

    The first observation of a task (no recent outputs) is fully novel (1.0). An
    output that matches a recent one after volatile-field normalization scores 0.0.
    """
    return 1.0 - max_similarity(output, recent_outputs, backend)


def _flatten_arguments(value: Any, path: str, tokens: set[str]) -> None:
    """Recursively add ``path:word`` tokens for every leaf of an argument tree."""
    if isinstance(value, Mapping):
        for key in value:
            _flatten_arguments(value[key], f"{path}.{key}" if path else str(key), tokens)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            _flatten_arguments(item, f"{path}[]", tokens)
    elif isinstance(value, str):
        words = _TOKEN.findall(normalize_volatile(value).lower())
        tokens.update(f"{path}:{word}" for word in words)
        if not words:
            tokens.add(f"{path}:")
    else:
        tokens.add(f"{path}:{value!s}".lower())


def argument_tokens(arguments: Mapping[str, Any]) -> frozenset[str]:
    """Return key-scoped word tokens (``key:word``) for a tool-argument mapping.

    Scoping tokens by key prevents two different arguments that merely share a
    common word from looking similar.
    """
    tokens: set[str] = set()
    _flatten_arguments(arguments, "", tokens)
    return frozenset(tokens)


def render_arguments(arguments: Mapping[str, Any]) -> str:
    """Render arguments as stable ``key=value`` text for pluggable text backends."""
    return "\n".join(sorted(argument_tokens(arguments)))


def argument_similarity(
    tool_a: str,
    arguments_a: Mapping[str, Any],
    tool_b: str,
    arguments_b: Mapping[str, Any],
    backend: SimilarityBackend | None = None,
) -> float:
    """Similarity of two tool calls' normalized arguments, 0.0 if the tools differ.

    Uses key-scoped token Jaccard by default; pass ``backend`` (for example an
    :class:`EmbeddingSimilarity`) to use a different measure.
    """
    if tool_a != tool_b:
        return 0.0
    if backend is not None:
        return backend.similarity(render_arguments(arguments_a), render_arguments(arguments_b))
    return jaccard(argument_tokens(arguments_a), argument_tokens(arguments_b))
