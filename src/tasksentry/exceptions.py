"""Exception hierarchy for TaskSentry.

Every error raised deliberately by the library derives from
:class:`TaskSentryError`, so callers can catch the whole family with one clause.
"""

from typing import Any


class TaskSentryError(Exception):
    """Base class for all TaskSentry errors."""


class ConfigurationError(TaskSentryError):
    """Raised when a configuration value is invalid or inconsistent."""


class ContractError(TaskSentryError):
    """Raised when a task contract is malformed or violates a contract rule."""


class StateError(TaskSentryError):
    """Raised when a canonical task state cannot be built or compared."""


class InformationGainError(TaskSentryError):
    """Raised when a belief update or information-gain computation is invalid."""


class BudgetError(TaskSentryError):
    """Base class for budget and resource accounting errors."""


class BudgetExceededError(BudgetError):
    """Raised when a hard budget limit would be or has been exceeded."""


class PricingError(TaskSentryError):
    """Base class for token pricing errors."""


class UnknownModelPriceError(PricingError):
    """Raised when a model is not found in the pricing table and no fallback exists."""


class ToolError(TaskSentryError):
    """Base class for tool definition, registration, and execution errors."""


class ToolRegistrationError(ToolError, ConfigurationError):
    """Raised when tool registration fails (e.g. duplicate name)."""


class ToolValidationError(ToolError):
    """Raised when tool arguments fail schema validation."""

    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class IsolationError(ToolError):
    """Raised when a tool cannot be isolated (e.g. unpicklable function/arguments)."""


class GovernorError(ToolError):
    """Raised when a tool action is rejected or blocked by the governor."""


class ModelError(TaskSentryError):
    """Base class for model invocation and client errors."""


class ModelNotFoundError(ModelError):
    """Raised when a requested model is not found in the model registry."""


class StorageError(TaskSentryError):
    """Base class for storage and receipt persistence errors."""


class StorageTaskNotFoundError(StorageError):
    """Raised when a task or receipt is not found in storage."""


class AgentRegistryError(TaskSentryError):
    """Base class for agent definition and resolution errors."""


class AgentNotFoundError(AgentRegistryError):
    """Raised when an agent definition is not found in the agent registry."""


class PolicyNotFoundError(AgentRegistryError):
    """Raised when an execution policy is not found."""
