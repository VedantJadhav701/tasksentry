"""The task contract: goal, objective success gates, milestones, budget, safety.

Every task must declare at least one *objective* success criterion backed by a
named deterministic verifier. Milestones are completed only when their
``done_when`` verifier passes; a model can propose completion but never mark a
milestone done by itself. Plain-string criteria are rejected on purpose.
"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tasksentry.core.state import CanonicalState, canonical_json, stable_hash
from tasksentry.exceptions import ContractError
from tasksentry.math.information_gain import (
    HypothesisBeliefTracker,
    TableLikelihoodModel,
)

VERIFIER_NAMES: frozenset[str] = frozenset(
    {
        "command_exit_code",
        "pytest",
        "json_schema",
        "file_exists",
        "git_diff_nonempty",
        "regex_match",
        "numeric_range",
        "python_assert",
        "artifact_exists",
    }
)

_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def _check_id(value: str) -> str:
    if not value or not set(value) <= _ID_CHARS:
        raise ValueError(f"invalid id {value!r}: use letters, digits, '_', '.', '-'")
    return value


def _check_verifier(value: str) -> str:
    if value not in VERIFIER_NAMES:
        raise ValueError(f"unknown verifier {value!r}; expected one of {sorted(VERIFIER_NAMES)}")
    return value


class VerifierSpec(BaseModel):
    """A reference to a deterministic verifier and its configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verifier: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("verifier")
    @classmethod
    def _validate_verifier(cls, value: str) -> str:
        return _check_verifier(value)


class SuccessCriterion(BaseModel):
    """A machine-checkable success criterion.

    Attributes:
        id: unique identifier within the contract.
        verifier: name of a deterministic verifier (see :data:`VERIFIER_NAMES`).
        config: verifier-specific configuration.
        required: whether this gate must pass for the task to count as successful.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    verifier: str
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool = True

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _check_id(value)

    @field_validator("verifier")
    @classmethod
    def _validate_verifier(cls, value: str) -> str:
        return _check_verifier(value)

    @property
    def spec(self) -> VerifierSpec:
        """The verifier reference of this criterion."""
        return VerifierSpec(verifier=self.verifier, config=self.config)


class Milestone(BaseModel):
    """A milestone completed only when its ``done_when`` verifier passes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    done_when: VerifierSpec

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _check_id(value)


class HypothesisSpec(BaseModel):
    """Hypothesis set for the Bayesian information-gain estimator.

    Attributes:
        priors: ``{hypothesis: P(h)}`` summing to 1 (at least two hypotheses).
        likelihoods: ``{observation: {hypothesis: P(observation | hypothesis)}}``.
        default_likelihood: likelihood for observations/hypotheses not listed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    priors: dict[str, float]
    likelihoods: dict[str, dict[str, float]] = Field(default_factory=dict)
    default_likelihood: float = Field(default=1.0, ge=0.0)

    @field_validator("priors")
    @classmethod
    def _priors_valid(cls, value: dict[str, float]) -> dict[str, float]:
        if len(value) < 2:
            raise ValueError("at least two hypotheses are required")
        if any(p < 0.0 for p in value.values()):
            raise ValueError("prior probabilities must be non-negative")
        if abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError("prior probabilities must sum to 1")
        return value

    def build_tracker(self) -> HypothesisBeliefTracker:
        """Create a :class:`HypothesisBeliefTracker` initialised from this spec."""
        model = TableLikelihoodModel(self.likelihoods, default=self.default_likelihood)
        return HypothesisBeliefTracker(self.priors, model)


class BudgetLimits(BaseModel):
    """Hard task-level limits. ``None`` means the dimension is unlimited."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_llm_calls: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0.0)
    max_wall_time_seconds: float | None = Field(default=None, gt=0.0)


class SafetyRules(BaseModel):
    """Safety rules attached to a contract.

    Attributes:
        allowed_tools: tool allowlist; ``None`` allows every registered tool.
        require_approval_for_writes: whether write actions need approval.
        max_risk: highest per-action risk (0..1) the task may incur.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_tools: tuple[str, ...] | None = None
    require_approval_for_writes: bool = True
    max_risk: float = Field(default=1.0, ge=0.0, le=1.0)


def _new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:8]}"


class TaskContract(BaseModel):
    """A complete task contract.

    Raises:
        pydantic.ValidationError: for malformed fields, unknown verifiers,
            plain-string criteria, an empty criteria list, or duplicate IDs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(default_factory=_new_task_id)
    goal: str = Field(min_length=1)
    success_criteria: list[SuccessCriterion] = Field(min_length=1)
    milestones: list[Milestone] = Field(default_factory=list)
    budget: BudgetLimits = Field(default_factory=BudgetLimits)
    safety: SafetyRules = Field(default_factory=SafetyRules)
    hypotheses: HypothesisSpec | None = None

    @field_validator("task_id")
    @classmethod
    def _validate_task_id(cls, value: str) -> str:
        return _check_id(value)

    @field_validator("goal")
    @classmethod
    def _goal_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("goal must not be blank")
        return value

    @model_validator(mode="after")
    def _unique_ids(self) -> "TaskContract":
        for label, ids in (
            ("success criterion", [c.id for c in self.success_criteria]),
            ("milestone", [m.id for m in self.milestones]),
        ):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {duplicates}")
        return self

    @property
    def criterion_ids(self) -> tuple[str, ...]:
        """IDs of all success criteria, in declaration order."""
        return tuple(c.id for c in self.success_criteria)

    @property
    def milestone_ids(self) -> tuple[str, ...]:
        """IDs of all milestones, in declaration order."""
        return tuple(m.id for m in self.milestones)

    @property
    def required_criteria(self) -> tuple[SuccessCriterion, ...]:
        """The success criteria that must pass for the task to succeed."""
        return tuple(c for c in self.success_criteria if c.required)

    def require_objective_gate(self) -> None:
        """Raise if no *required* objective gate exists.

        Raises:
            ContractError: if every criterion is marked ``required=False``.
        """
        if not self.required_criteria:
            raise ContractError("a contract needs at least one required objective gate")

    def initial_state(self, world: dict[str, Any] | None = None) -> CanonicalState:
        """Build the initial canonical state ``s_0`` for this contract."""
        return CanonicalState(
            goal=self.goal,
            criteria_ids=self.criterion_ids,
            world=dict(world or {}),
        )

    def digest(self) -> str:
        """Return a stable hash of the goal, criteria, and milestones."""
        payload = {
            "goal": self.goal,
            "criteria": [c.model_dump(mode="json") for c in self.success_criteria],
            "milestones": [m.model_dump(mode="json") for m in self.milestones],
        }
        return stable_hash(canonical_json(payload, for_state=False))

    def build_belief_tracker(self) -> HypothesisBeliefTracker | None:
        """Return a belief tracker if the contract defines hypotheses, else ``None``."""
        return self.hypotheses.build_tracker() if self.hypotheses else None
