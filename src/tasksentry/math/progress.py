"""Agent Progress Gain (APG), rolling window, EMA, and the loop-stop policy.

All weights and thresholds below are *configurable heuristic defaults*, not
constants derived from theory. They should be tuned and ablated on real tasks.

Equations
---------
Agent Progress Gain of step ``t``::

    APG_t =   a1 * StateChange_t
            + a2 * MilestoneProgress_t
            + a3 * EstimatedInformationGain_t
            + a4 * EvidenceNovelty_t
            - a5 * EffectiveRepetitionPenalty_t
            - a6 * NormalizedCost_t

with defaults ``a1=1.0, a2=1.0, a3=0.8, a4=0.8, a5=2.0, a6=0.1``.

Terms::

    StateChange_t       = 1 if canonical_state_hash(s_{t+1}) != canonical_state_hash(s_t) else 0
    MilestoneProgress_t = |M_{t+1}| - |M_t|
    EvidenceNovelty_t   = 1 - max_similarity(o_t, recent normalized outputs)
    NormalizedCost_t    = min(cost_t / cost_cap, 1)

Repetition penalty (never above 2.0 per step)::

    EffectiveRepetitionPenalty_t = 0                                    if any exemption applies
                                 = min(2, [exact fingerprint in last 10 actions]
                                          + [semantic argument similarity > 0.92])  otherwise

Rolling window and exponential moving average::

    WindowGain_t = sum(APG_{t-n+1} .. APG_t)                  (default n = 5)
    EMA_t        = beta * APG_t + (1 - beta) * EMA_{t-1}      (default beta = 0.3, EMA_0 = 0)

Canonical loop policy (one policy, applied to ``WindowGain_t``)::

    fewer than n steps         -> continue                          (reason: cold_start)
    WindowGain >  0            -> continue
    WindowGain == 0            -> warn_and_require_new_approach
    -1 < WindowGain < 0        -> warn_and_require_new_approach
    -2 < WindowGain <= -1      -> force_replan
    WindowGain <= -2           -> stop_or_escalate

Blocked duplicate calls are *not* part of the window. They receive a separate
fixed controller penalty of -0.5, are counted separately, and escalate only
after three blocked calls in one task.
"""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.math.similarity import (
    JaccardSimilarity,
    SimilarityBackend,
    argument_similarity,
    evidence_novelty,
    normalize_volatile,
)

_EPSILON_DIGITS = 9
MAX_REPETITION_PENALTY = 2.0


class APGWeights(BaseModel):
    """Weights ``alpha_1..alpha_6`` of the APG formula (configurable heuristics)."""

    model_config = ConfigDict(frozen=True)

    alpha_1: float = 1.0  # state change
    alpha_2: float = 1.0  # milestone progress
    alpha_3: float = 0.8  # estimated information gain
    alpha_4: float = 0.8  # evidence novelty
    alpha_5: float = 2.0  # effective repetition penalty
    alpha_6: float = 0.1  # normalized cost


class ProgressConfig(BaseModel):
    """Configuration for :class:`ProgressTracker`.

    Attributes:
        weights: the APG weights.
        window: rolling-window length ``n``.
        beta: EMA smoothing factor in ``(0, 1]``.
        cost_cap: per-step cost (USD) at which the cost term saturates.
        recent_actions: how many recent actions/outputs are remembered.
        semantic_threshold: argument similarity above which a call counts as a
            semantic repeat.
        new_evidence_threshold: novelty at or above which a retry counts as having
            produced new evidence (an exemption).
        block_threshold: fingerprint count in the recent window that blocks a call.
        blocked_penalty: fixed controller penalty per blocked duplicate.
        escalate_after_blocks: blocked calls per task before escalation.
    """

    model_config = ConfigDict(frozen=True)

    weights: APGWeights = Field(default_factory=APGWeights)
    window: int = Field(default=5, ge=1)
    beta: float = Field(default=0.3, gt=0.0, le=1.0)
    cost_cap: float = Field(default=0.10, gt=0.0)
    recent_actions: int = Field(default=10, ge=1)
    semantic_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    new_evidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    block_threshold: int = Field(default=2, ge=1)
    blocked_penalty: float = -0.5
    escalate_after_blocks: int = Field(default=3, ge=1)


class LoopAction(StrEnum):
    """The controller decision derived from the rolling window gain."""

    CONTINUE = "continue"
    WARN = "warn_and_require_new_approach"
    REPLAN = "force_replan"
    STOP = "stop_or_escalate"


@dataclass(frozen=True)
class LoopVerdict:
    """A loop-policy decision with its reason and the window gain it was based on."""

    action: LoopAction
    reason: str
    window_gain: float


def evaluate_loop_policy(window_gain: float, history_len: int, window: int = 5) -> LoopVerdict:
    """Apply the canonical stop policy to a window gain.

    Args:
        window_gain: ``WindowGain_t``.
        history_len: number of scored steps so far.
        window: window length ``n``; fewer than ``n`` steps is a cold start.
    """
    gain = round(window_gain, _EPSILON_DIGITS)
    if history_len < window:
        return LoopVerdict(LoopAction.CONTINUE, "cold_start", window_gain)
    if gain > 0:
        return LoopVerdict(LoopAction.CONTINUE, "window_gain_positive", window_gain)
    if gain == 0:
        return LoopVerdict(LoopAction.WARN, "window_gain_zero", window_gain)
    if -1.0 < gain < 0:
        return LoopVerdict(LoopAction.WARN, "window_gain_slightly_negative", window_gain)
    if -2.0 < gain <= -1.0:
        return LoopVerdict(LoopAction.REPLAN, "window_gain_requires_replan", window_gain)
    return LoopVerdict(LoopAction.STOP, "window_gain_at_stop_threshold", window_gain)


def state_change(hash_before: str, hash_after: str) -> int:
    """Return ``StateChange_t``: 1 if the canonical state hash changed, else 0."""
    return 1 if hash_before != hash_after else 0


def milestone_progress(milestones_before: int, milestones_after: int) -> int:
    """Return ``MilestoneProgress_t = |M_{t+1}| - |M_t|``."""
    return milestones_after - milestones_before


def normalized_cost(cost: float, cost_cap: float) -> float:
    """Return ``min(cost / cost_cap, 1)``, clamped below at 0.

    Raises:
        ValueError: if ``cost_cap`` is not positive.
    """
    if cost_cap <= 0.0:
        raise ValueError("cost_cap must be positive")
    return min(max(cost, 0.0) / cost_cap, 1.0)


def ema_update(previous: float, apg: float, beta: float) -> float:
    """Return ``beta * APG_t + (1 - beta) * EMA_{t-1}``."""
    return beta * apg + (1.0 - beta) * previous


@dataclass(frozen=True)
class RetryExemptions:
    """Reasons a repeated action is productive rather than wasteful.

    Any true flag zeroes the repetition penalty. The first six flags are the
    contract exemptions; ``milestone_progress`` is derived because a repeat that
    completes a milestone is by definition not wasteful.
    """

    previous_transient_failure: bool = False
    arguments_changed: bool = False
    durable_state_changed: bool = False
    previous_observation_error: bool = False
    new_evidence: bool = False
    idempotent_safe: bool = False
    milestone_progress: bool = False

    @property
    def any(self) -> bool:
        """True if at least one exemption applies."""
        return bool(self.active)

    @property
    def active(self) -> tuple[str, ...]:
        """Names of the exemptions that apply."""
        return tuple(name for name, flag in self.__dict__.items() if flag)

    def merged(self, other: "RetryExemptions") -> "RetryExemptions":
        """Return the union of two exemption sets."""
        return RetryExemptions(
            **{name: flag or other.__dict__[name] for name, flag in self.__dict__.items()}
        )


def effective_repetition_penalty(
    *, exact_repeat: bool, semantic_repeat: bool, exempt: bool
) -> float:
    """Return the repetition penalty: 0 if exempt, else ``min(2, exact + semantic)``."""
    if exempt:
        return 0.0
    return min(MAX_REPETITION_PENALTY, float(exact_repeat) + float(semantic_repeat))


@dataclass(frozen=True)
class APGComponents:
    """The unweighted terms of one APG computation."""

    state_change: int
    milestone_progress: int
    information_gain: float
    evidence_novelty: float
    repetition_penalty: float
    normalized_cost: float


@dataclass(frozen=True)
class APGBreakdown:
    """Unweighted terms, weighted contributions, and the resulting APG."""

    components: APGComponents
    weighted: dict[str, float]
    apg: float


def compute_apg(components: APGComponents, weights: APGWeights | None = None) -> APGBreakdown:
    """Compute ``APG_t`` from its components and weights (see module docstring)."""
    w = weights or APGWeights()
    weighted = {
        "state_change": w.alpha_1 * components.state_change,
        "milestone_progress": w.alpha_2 * components.milestone_progress,
        "information_gain": w.alpha_3 * components.information_gain,
        "evidence_novelty": w.alpha_4 * components.evidence_novelty,
        "repetition_penalty": -w.alpha_5 * components.repetition_penalty,
        "cost": -w.alpha_6 * components.normalized_cost,
    }
    return APGBreakdown(components=components, weighted=weighted, apg=sum(weighted.values()))


@dataclass(frozen=True)
class StepScore:
    """Everything the tracker computed for one executed step."""

    apg: float
    breakdown: APGBreakdown
    window_gain: float
    ema: float
    verdict: LoopVerdict
    exact_repeat: bool
    semantic_repeat: bool
    exemptions: RetryExemptions
    is_wasted: bool


@dataclass(frozen=True)
class BlockOutcome:
    """The result of registering a blocked duplicate call."""

    blocked_count: int
    penalty: float
    total_controller_penalty: float
    escalate: bool


@dataclass(frozen=True)
class _ActionRecord:
    tool: str
    arguments: Mapping[str, Any]
    fingerprint: str
    state_hash_at_call: str
    is_error: bool
    is_transient_failure: bool


@dataclass
class _TrackerState:
    window: deque[float]
    actions: deque[_ActionRecord]
    outputs: deque[str]
    ema: float = 0.0
    steps: int = 0
    blocked: int = 0
    controller_penalty: float = 0.0
    wasted: int = 0
    scores: list[float] = field(default_factory=list)


class ProgressTracker:
    """Scores executed steps with APG and applies the canonical loop policy.

    One tracker holds the rolling state for one task. It is deterministic and
    has no global state.

    Args:
        config: weights and thresholds (heuristic defaults if omitted).
        backend: similarity backend for evidence novelty (token Jaccard by default).
        argument_backend: optional backend for argument similarity; if omitted,
            key-scoped token Jaccard is used.
    """

    def __init__(
        self,
        config: ProgressConfig | None = None,
        backend: SimilarityBackend | None = None,
        argument_backend: SimilarityBackend | None = None,
    ) -> None:
        self.config = config or ProgressConfig()
        self._backend: SimilarityBackend = backend or JaccardSimilarity()
        self._argument_backend = argument_backend
        self._state = _TrackerState(
            window=deque(maxlen=self.config.window),
            actions=deque(maxlen=self.config.recent_actions),
            outputs=deque(maxlen=self.config.recent_actions),
        )

    # ------------------------------------------------------------------ queries
    @property
    def history_len(self) -> int:
        """Number of executed steps scored so far."""
        return self._state.steps

    @property
    def ema(self) -> float:
        """Current exponential moving average of APG."""
        return self._state.ema

    @property
    def scores(self) -> tuple[float, ...]:
        """Every APG score recorded so far, in order."""
        return tuple(self._state.scores)

    @property
    def wasted_steps(self) -> int:
        """Number of executed steps classified as wasted (APG <= 0)."""
        return self._state.wasted

    @property
    def blocked_count(self) -> int:
        """Number of duplicate calls blocked so far."""
        return self._state.blocked

    @property
    def controller_penalty_total(self) -> float:
        """Sum of the separate blocked-call penalties (kept out of the window)."""
        return self._state.controller_penalty

    def window_gain(self) -> float:
        """Return ``WindowGain_t``, the sum of APG over the last ``n`` steps."""
        return sum(self._state.window)

    def decision(self) -> LoopVerdict:
        """Apply the canonical loop policy to the current window gain."""
        return evaluate_loop_policy(self.window_gain(), self._state.steps, self.config.window)

    def fingerprint_count(self, fingerprint: str) -> int:
        """Count how often ``fingerprint`` appears in the recent executed actions."""
        return sum(1 for record in self._state.actions if record.fingerprint == fingerprint)

    def should_block(self, fingerprint: str, exemptions: RetryExemptions | None = None) -> bool:
        """Return true if the call must be blocked before execution.

        A call is blocked when its fingerprint already appears at least
        ``block_threshold`` (default 2) times among the last ``recent_actions``
        executed actions and no retry exemption applies.
        """
        if exemptions is not None and exemptions.any:
            return False
        return self.fingerprint_count(fingerprint) >= self.config.block_threshold

    def register_blocked_duplicate(self) -> BlockOutcome:
        """Record a blocked duplicate call.

        The call is not executed, is not added to the action history, does not
        feed evidence novelty, and does not enter ``WindowGain``. It carries the
        fixed controller penalty and escalates after ``escalate_after_blocks``.
        """
        self._state.blocked += 1
        penalty = self.config.blocked_penalty
        self._state.controller_penalty += penalty
        return BlockOutcome(
            blocked_count=self._state.blocked,
            penalty=penalty,
            total_controller_penalty=self._state.controller_penalty,
            escalate=self._state.blocked >= self.config.escalate_after_blocks,
        )

    # ------------------------------------------------------------------ scoring
    def score_step(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        output: str,
        fingerprint: str,
        state_hash_before: str,
        state_hash_after: str,
        milestones_before: int,
        milestones_after: int,
        cost_usd: float = 0.0,
        estimated_information_gain: float = 0.0,
        exemptions: RetryExemptions | None = None,
        is_error: bool = False,
        is_transient_failure: bool = False,
    ) -> StepScore:
        """Score one executed step, update the window and EMA, and return the result.

        Args:
            tool_name: tool that was executed.
            arguments: its arguments.
            output: the tool output (normalized internally before comparison).
            fingerprint: action fingerprint computed at call time
                (see :func:`tasksentry.core.state.action_fingerprint`).
            state_hash_before: canonical state hash at call time.
            state_hash_after: canonical state hash after the step.
            milestones_before: ``|M_t|``.
            milestones_after: ``|M_{t+1}|``.
            cost_usd: cost of this step in USD.
            estimated_information_gain: output of an information-gain estimator.
            exemptions: caller-supplied exemptions, merged with derived ones.
            is_error: whether this step's observation was an error.
            is_transient_failure: whether this step failed with a transient error.
        """
        cfg = self.config
        novelty = evidence_novelty(output, self._state.outputs, self._backend)

        exact_repeat = any(r.fingerprint == fingerprint for r in self._state.actions)
        similar = [
            r
            for r in self._state.actions
            if argument_similarity(
                r.tool, r.arguments, tool_name, arguments, self._argument_backend
            )
            > cfg.semantic_threshold
        ]
        semantic_repeat = bool(similar)

        after_changed = state_change(state_hash_before, state_hash_after)
        previous = similar[-1] if similar else None
        derived = RetryExemptions(
            previous_transient_failure=bool(previous and previous.is_transient_failure),
            previous_observation_error=bool(previous and previous.is_error),
            durable_state_changed=bool(after_changed)
            or (bool(similar) and all(r.state_hash_at_call != state_hash_before for r in similar)),
            new_evidence=novelty >= cfg.new_evidence_threshold,
            milestone_progress=milestones_after > milestones_before,
        )
        merged = derived.merged(exemptions) if exemptions else derived

        penalty = effective_repetition_penalty(
            exact_repeat=exact_repeat, semantic_repeat=semantic_repeat, exempt=merged.any
        )
        components = APGComponents(
            state_change=after_changed,
            milestone_progress=milestone_progress(milestones_before, milestones_after),
            information_gain=estimated_information_gain,
            evidence_novelty=novelty,
            repetition_penalty=penalty,
            normalized_cost=normalized_cost(cost_usd, cfg.cost_cap),
        )
        breakdown = compute_apg(components, cfg.weights)

        st = self._state
        st.window.append(breakdown.apg)
        st.ema = ema_update(st.ema, breakdown.apg, cfg.beta)
        st.steps += 1
        st.scores.append(breakdown.apg)
        is_wasted = breakdown.apg <= 0.0
        if is_wasted:
            st.wasted += 1
        st.actions.append(
            _ActionRecord(
                tool=tool_name,
                arguments=dict(arguments),
                fingerprint=fingerprint,
                state_hash_at_call=state_hash_before,
                is_error=is_error,
                is_transient_failure=is_transient_failure,
            )
        )
        st.outputs.append(normalize_volatile(output))

        return StepScore(
            apg=breakdown.apg,
            breakdown=breakdown,
            window_gain=self.window_gain(),
            ema=st.ema,
            verdict=self.decision(),
            exact_repeat=exact_repeat,
            semantic_repeat=semantic_repeat,
            exemptions=merged,
            is_wasted=is_wasted,
        )


__all__ = [
    "MAX_REPETITION_PENALTY",
    "APGBreakdown",
    "APGComponents",
    "APGWeights",
    "BlockOutcome",
    "LoopAction",
    "LoopVerdict",
    "ProgressConfig",
    "ProgressTracker",
    "RetryExemptions",
    "StepScore",
    "compute_apg",
    "effective_repetition_penalty",
    "ema_update",
    "evaluate_loop_policy",
    "milestone_progress",
    "normalized_cost",
    "state_change",
]
