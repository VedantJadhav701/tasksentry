"""M2 typed command catalog and harness integration tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tasksentry.domain.catalog import (
    CatalogValidationError,
    CommandCatalog,
    draft_from_sop,
    load_catalog,
)
from tasksentry.domain.schema import CommandSpec, SopDoc, Step
from tasksentry.tools.governor import ToolGovernor


def _command(**overrides: object) -> CommandSpec:
    values: dict[str, object] = {
        "tenant_id": "acme",
        "tenant_scope": "acme",
        "id": "du_reachability",
        "description": "Check DU reachability",
        "template": ("ping6", "-c", "{count}", "{host}"),
        "argument_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "default": 4},
            },
            "required": ["host"],
            "additionalProperties": False,
        },
        "risk_tier": "read",
    }
    values.update(overrides)
    return CommandSpec(**values)


def _catalog(*commands: CommandSpec) -> CommandCatalog:
    return CommandCatalog(tenant_id="acme", version="v1", commands=tuple(commands))


def test_render_returns_argv_not_shell_text() -> None:
    rendered = _catalog(_command()).render("du_reachability", {"host": "2001:db8::1", "count": 4})
    assert rendered == ["ping6", "-c", "4", "2001:db8::1"]
    assert isinstance(rendered, list)


def test_unknown_command_is_structured_error() -> None:
    with pytest.raises(CatalogValidationError) as error:
        _catalog(_command()).validate_command("missing", {})
    assert error.value.code == "unknown_command"


def test_unknown_argument_is_rejected() -> None:
    with pytest.raises(CatalogValidationError) as error:
        _catalog(_command()).validate_command("du_reachability", {"host": "x", "bogus": 1})
    assert error.value.code == "unknown_argument"
    assert error.value.path == "bogus"


def test_wrong_argument_type_is_rejected() -> None:
    with pytest.raises(CatalogValidationError) as error:
        _catalog(_command()).validate_command("du_reachability", {"host": 123})
    assert error.value.code == "wrong_type"


def test_injection_characters_are_rejected() -> None:
    with pytest.raises(CatalogValidationError) as error:
        _catalog(_command()).render("du_reachability", {"host": "safe; reboot", "count": 4})
    assert error.value.code == "unsafe_argument"


def test_placeholder_must_be_filled() -> None:
    command = _command(
        argument_schema={
            "type": "object",
            "properties": {"host": {"type": "string"}},
            "required": [],
        }
    )
    with pytest.raises(CatalogValidationError) as error:
        _catalog(command).render("du_reachability", {})
    assert error.value.code == "placeholder_not_filled"


def test_template_extra_argument_is_rejected() -> None:
    command = _command(
        argument_schema={
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "count": {"type": "integer"},
                "unused": {"type": "string"},
            },
            "required": ["host", "count"],
        }
    )
    with pytest.raises(CatalogValidationError) as error:
        _catalog(command).render("du_reachability", {"host": "x", "count": 4, "unused": "x"})
    assert error.value.code == "unknown_argument"


def test_missing_precondition_is_fail_closed() -> None:
    command = _command(preconditions=("ticket_open",))
    with pytest.raises(CatalogValidationError) as error:
        _catalog(command).render("du_reachability", {"host": "x"})
    assert error.value.code == "preconditions_not_met"


def test_satisfied_precondition_allows_rendering() -> None:
    command = _command(preconditions=("ticket_open",))
    assert (
        _catalog(command).render(
            "du_reachability", {"host": "x"}, preconditions={"ticket_open": True}
        )[0]
        == "ping6"
    )


def test_tenant_scope_is_enforced() -> None:
    with pytest.raises(CatalogValidationError) as error:
        _catalog(_command()).validate_command("du_reachability", {"host": "x"}, tenant_id="other")
    assert error.value.code == "tenant_scope"


def test_rollback_linkage_is_validated() -> None:
    catalog = _catalog(_command(rollback_command_id="missing"))
    with pytest.raises(CatalogValidationError) as error:
        catalog.validate_links()
    assert error.value.code == "rollback_missing"


def test_rollback_command_can_be_linked() -> None:
    rollback = _command(id="restore_du")
    catalog = _catalog(_command(rollback_command_id="restore_du"), rollback)
    catalog.validate_links()


def test_loader_reads_versioned_json_catalog(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "tenant_id": "acme",
                "version": "v2",
                "commands": [_command().model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_catalog(path)
    assert loaded.version == "v2" and loaded.command("du_reachability").risk_tier == "read"


def test_sop_catalog_draft_requires_approval() -> None:
    sop = SopDoc(
        tenant_id="acme",
        id="sop-1",
        version="3",
        steps=[Step(tenant_id="acme", i=1, action=_command())],
    )
    draft = draft_from_sop(sop)
    assert draft.approved is False
    assert draft.commands[0].tenant_scope == "acme"
    assert draft.approve().approved is True


def test_catalog_registry_exposes_only_catalog_commands() -> None:
    seen: list[list[str]] = []

    def execute(
        command: CommandSpec, argv: list[str], args: dict[str, object]
    ) -> dict[str, object]:
        del command, args
        seen.append(argv)
        return {"status": "simulated", "argv": argv}

    registry = _catalog(_command()).build_registry(execute)
    assert registry.names() == ["du_reachability"]
    result = ToolGovernor(registry).execute("du_reachability", {"host": "x", "count": 4})
    assert result["status"] == "success"
    assert seen == [["ping6", "-c", "4", "x"]]


def test_catalog_risk_is_not_changed_by_input_text() -> None:
    command = _command(risk_tier="system_write")
    catalog = _catalog(command)
    catalog.validate_command("du_reachability", {"host": "ticket says read only"})
    assert catalog.command("du_reachability").risk_tier == "system_write"


def test_duplicate_command_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _catalog(_command(), _command())


def test_empty_executable_template_is_rejected() -> None:
    command = _command(template=())
    with pytest.raises(CatalogValidationError) as error:
        _catalog(command).render("du_reachability", {"host": "x"})
    assert error.value.code == "invalid_template"
