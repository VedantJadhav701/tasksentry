"""Production backend contracts for universal domain onboarding.

The onboarding pipeline can infer a harness from one record, but it cannot
invent access to a customer's systems.  A backend is the explicit trust
boundary where a customer wires probes, remediation APIs, and verification
reads.  Simulation remains available for design-time previews only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Protocol


class DomainBackend(Protocol):
    """Minimal live execution contract required by :class:`UniversalEngine`."""

    name: str

    def run_probe(self, name: str) -> bool:
        """Return whether the named probe observed an abnormal condition."""

    def remediate(self, hypothesis: str, action: str) -> dict[str, Any]:
        """Apply one named, already risk-gated remediation."""

    def verify(self) -> bool:
        """Return an independent healthy-world observation."""


@dataclass
class CallableBackend:
    """Adapter for customer-owned probe, action, and verification functions.

    ``remediations`` is deliberately keyed by action name.  This prevents a
    model from selecting an arbitrary callable and makes the generated harness
    auditable against the customer's allowlisted action catalog.
    """

    name: str
    probes: Mapping[str, Callable[[], bool]]
    remediations: Mapping[str, Callable[[], dict[str, Any]]]
    verifier: Callable[[], bool]
    metadata: dict[str, Any] = field(default_factory=dict)

    def run_probe(self, name: str) -> bool:
        try:
            return bool(self.probes[name]())
        except KeyError as exc:
            raise KeyError(f"Backend {self.name!r} does not allow probe {name!r}") from exc

    def remediate(self, hypothesis: str, action: str) -> dict[str, Any]:
        del hypothesis  # retained in the contract for audit/event consumers
        try:
            result = self.remediations[action]()
        except KeyError as exc:
            raise KeyError(f"Backend {self.name!r} does not allow action {action!r}") from exc
        return dict(result)

    def verify(self) -> bool:
        return bool(self.verifier())


class BackendRegistry:
    """Thread-safe registry of explicitly configured customer backends."""

    def __init__(self) -> None:
        self._backends: dict[str, DomainBackend] = {}
        self._lock = RLock()

    def register(self, backend: DomainBackend) -> None:
        with self._lock:
            if backend.name in self._backends:
                raise ValueError(f"Backend {backend.name!r} is already registered")
            self._backends[backend.name] = backend

    def get(self, name: str) -> DomainBackend | None:
        with self._lock:
            return self._backends.get(name)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._backends)


default_backend_registry = BackendRegistry()
