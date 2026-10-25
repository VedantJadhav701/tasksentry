"""Exception hierarchy for TaskSentry.

Every error raised deliberately by the library derives from
:class:`TaskSentryError`, so callers can catch the whole family with one clause.
"""


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
