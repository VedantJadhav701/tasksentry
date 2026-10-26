import pytest
from pydantic import BaseModel

from tasksentry.harness.backend import CallableBackend
from tasksentry.harness.engine import UniversalEngine
from tasksentry.telecom.pack import build_from_state
from tasksentry.telecom.tools import TelecomSimulationState
from tasksentry.tools.governor import ToolGovernor
from tasksentry.tools.registry import Tool, ToolRegistry


def test_system_write_requires_approval() -> None:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="power",
            input_model=BaseModel,
            callable=lambda: {"status": "SUCCESS"},
            risk="system_write",
        )
    )

    result = ToolGovernor(registry).execute("power", {})

    assert result["status"] == "blocked"
    assert result["reason"] == "write_approval_required"


def test_live_backend_adapter_is_allowlisted() -> None:
    called: list[str] = []
    backend = CallableBackend(
        name="customer",
        probes={"pods": lambda: called.append("probe") or True},
        remediations={"restart": lambda: {"status": "SUCCESS"}},
        verifier=lambda: True,
    )

    assert backend.run_probe("pods") is True
    assert backend.remediate("software", "restart")["status"] == "SUCCESS"
    with pytest.raises(KeyError, match="does not allow probe"):
        backend.run_probe("shell")
    assert called == ["probe"]


def test_signed_universal_receipt() -> None:
    result = UniversalEngine(
        build_from_state(TelecomSimulationState.from_ticket_failure_type("softwarefailure")),
        signing_key=b"test-key",
    ).solve()

    assert result.chain_valid is True
    assert result.chain_signed is True
