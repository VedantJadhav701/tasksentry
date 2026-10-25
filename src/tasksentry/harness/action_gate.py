"""Action gate verifying completion claims and dispatching governed actions."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.core.contract import TaskContract
from tasksentry.core.events import VERIFICATION_FAILED, Event
from tasksentry.core.state import CanonicalState
from tasksentry.harness.verification import VerificationGate
from tasksentry.math.progress import RetryExemptions
from tasksentry.tools.governor import ToolGovernor


class GovernedActionVerdict(BaseModel):
    """Decision produced by the ActionGate prior to execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    is_completion_claim: bool = False
    rejection_reason: str | None = None
    action_payload: dict[str, Any] = Field(default_factory=dict)
    verification_results: list[dict[str, Any]] = Field(default_factory=list)


class ActionGate:
    """Gatekeeper regulating tool invocations and completion claims."""

    def __init__(
        self,
        governor: ToolGovernor,
        contract: TaskContract,
        verification_gate: VerificationGate | None = None,
    ) -> None:
        self.governor = governor
        self.contract = contract
        self.verification_gate = verification_gate or VerificationGate()
        self._events: list[Event] = []

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> Event:
        event = Event(type=event_type, message=message, data=data or {})
        self._events.append(event)
        return event

    def evaluate_action(
        self,
        action: dict[str, Any],
        *,
        canonical_state: CanonicalState | None = None,
        context: dict[str, Any] | None = None,
        exemptions: RetryExemptions | None = None,
        approved_write: bool = False,
    ) -> GovernedActionVerdict:
        """Validate and govern proposed action.

        If action claims task completion ('complete_task' or 'finish'):
        - Runs all required success criteria verifiers.
        - If any fail, rejects completion and emits VERIFICATION_FAILED.

        If action is a tool call:
        - Evaluates governor safety, allowlists, schema, and loop rules.
        """
        action_type = action.get("type", "tool_call")

        # 1. Completion claim evaluation
        if action_type in ("complete_task", "finish", "complete"):
            all_passed, results = self.verification_gate.all_required_passed(
                self.contract.success_criteria,
                context=context or {},
            )
            serial_results = [r.model_dump() for r in results]

            if not all_passed:
                failed_msgs = [r.message for r in results if not r.passed]
                msg = (
                    f"Completion claim rejected: {len(failed_msgs)} "
                    "required verification gates failed."
                )
                self._emit(VERIFICATION_FAILED, msg, {"failed": failed_msgs})
                return GovernedActionVerdict(
                    allowed=False,
                    is_completion_claim=True,
                    rejection_reason=msg,
                    action_payload=action,
                    verification_results=serial_results,
                )

            return GovernedActionVerdict(
                allowed=True,
                is_completion_claim=True,
                rejection_reason=None,
                action_payload=action,
                verification_results=serial_results,
            )

        # 2. Tool call governance
        tool_name = action.get("tool") or action.get("name")
        arguments = action.get("arguments", {})

        if not tool_name:
            return GovernedActionVerdict(
                allowed=False,
                rejection_reason="Action missing required 'tool' name",
                action_payload=action,
            )

        # Pre-check tool existence
        tool = self.governor.registry.get(tool_name)
        if tool is None:
            return GovernedActionVerdict(
                allowed=False,
                rejection_reason=f"Tool {tool_name!r} not found in registry",
                action_payload=action,
            )

        # Check schema validity
        try:
            valid_args = tool.validate_args(arguments)
        except Exception as exc:
            return GovernedActionVerdict(
                allowed=False,
                rejection_reason=f"Argument schema validation failed: {exc}",
                action_payload=action,
            )

        # Check budget
        if self.governor.budget is not None and not self.governor.budget.can_afford(tool_calls=1):
            return GovernedActionVerdict(
                allowed=False,
                rejection_reason=f"Budget cannot afford tool call for {tool_name!r}",
                action_payload=action,
            )

        # Check duplicate fingerprint rule
        s_hash = canonical_state.state_hash() if canonical_state is not None else "0" * 64
        from tasksentry.core.state import action_fingerprint

        fp = action_fingerprint(tool_name, valid_args, s_hash)
        fp_count = self.governor.tracker.fingerprint_count(fp)

        effective_exemptions = exemptions or RetryExemptions()
        if tool.idempotent:
            effective_exemptions = effective_exemptions.merged(
                RetryExemptions(idempotent_safe=True)
            )

        if (
            fp_count >= self.governor.tracker.config.block_threshold
            and not effective_exemptions.any
        ):
            # Blocked duplicate
            return GovernedActionVerdict(
                allowed=False,
                rejection_reason="Duplicate action fingerprint threshold exceeded",
                action_payload=action,
            )

        return GovernedActionVerdict(
            allowed=True,
            is_completion_claim=False,
            action_payload={"tool": tool_name, "arguments": valid_args},
        )
