"""Typed, reviewable command catalogs for domain runs.

Commands are catalog IDs with validated arguments.  Rendering produces an
argument vector for an explicitly configured backend; no model output is ever
treated as a shell command.
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, create_model

from tasksentry.domain.schema import CommandSpec, SopDoc
from tasksentry.tools.registry import Tool, ToolRegistry

RiskTier = Literal["read", "reversible_write", "system_write", "destructive"]
_RISK_ORDER = {"read": 0, "reversible_write": 1, "system_write": 2, "destructive": 3}
_UNSAFE_ARGUMENTS = re.compile(r"[\x00\r\n;&|`$]")


class CatalogValidationError(ValueError):
    """Structured command validation failure."""

    def __init__(self, code: str, message: str, *, path: str = "") -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


class CatalogDraft(BaseModel):
    """Human-reviewable catalog proposal; drafts cannot be executed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    commands: tuple[CommandSpec, ...] = Field(default_factory=tuple)
    approved: bool = False
    source_step_ids: tuple[str, ...] = Field(default_factory=tuple)

    def approve(self) -> CatalogDraft:
        """Return an approved copy after an explicit human action."""
        return self.model_copy(update={"approved": True})


def _schema_type(value: Any) -> type[Any]:
    mapping: dict[str, type[Any]] = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list[Any],
        "object": dict[str, Any],
    }
    return mapping.get(str(value), Any)


def _input_model(spec: CommandSpec) -> type[BaseModel]:
    properties = spec.argument_schema.get("properties", {})
    required = set(spec.argument_schema.get("required", []))
    if not isinstance(properties, Mapping):
        properties = {}
    fields: dict[str, tuple[Any, Any]] = {}
    for name, definition in properties.items():
        definition = definition if isinstance(definition, Mapping) else {}
        annotation = _schema_type(definition.get("type"))
        default: Any = ... if name in required else definition.get("default", None)
        fields[str(name)] = (annotation, default)
    return cast(
        type[BaseModel],
        create_model(
            f"CatalogArgs_{spec.id.replace('-', '_')}",
            __config__=ConfigDict(extra="forbid"),
            **cast(Any, fields),
        ),
    )


class CommandCatalog(BaseModel):
    """Versioned commands for exactly one tenant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    commands: tuple[CommandSpec, ...] = Field(min_length=1)

    def model_post_init(self, __context: Any) -> None:
        """Reject duplicate IDs immediately while keeping rollback checks explicit."""
        del __context
        ids = [command.id for command in self.commands]
        if len(ids) != len(set(ids)):
            raise CatalogValidationError("duplicate_command", "Command IDs must be unique.")

    def command(self, command_id: str) -> CommandSpec:
        for command in self.commands:
            if command.id == command_id:
                return command
        raise CatalogValidationError("unknown_command", f"Unknown catalog command {command_id!r}.")

    def _check_template(self, command: CommandSpec, args: Mapping[str, Any]) -> None:
        fields: set[str] = set()
        formatter = string.Formatter()
        if not command.template:
            raise CatalogValidationError(
                "invalid_template", "Executable commands need a non-empty argv template."
            )
        for part in command.template:
            if not isinstance(part, str) or not part:
                raise CatalogValidationError(
                    "invalid_template", "Template entries must be non-empty strings."
                )
            if _UNSAFE_ARGUMENTS.search(part):
                raise CatalogValidationError(
                    "unsafe_template", "Command templates cannot contain shell control characters."
                )
            try:
                parsed = list(formatter.parse(part))
            except ValueError as exc:
                raise CatalogValidationError("invalid_template", str(exc)) from exc
            for _, field_name, format_spec, conversion in parsed:
                if field_name is not None:
                    if not field_name.isidentifier() or format_spec or conversion:
                        raise CatalogValidationError(
                            "invalid_placeholder",
                            f"Template placeholder {field_name!r} must be a plain argument name.",
                        )
                    fields.add(field_name)
        missing = fields - set(args)
        if missing:
            raise CatalogValidationError(
                "placeholder_not_filled",
                f"Missing template arguments: {sorted(missing)}.",
            )
        extra = set(args) - fields
        if extra and command.template:
            raise CatalogValidationError(
                "unknown_argument", f"Arguments are not used by the template: {sorted(extra)}."
            )

    def _check_schema(self, command: CommandSpec, args: Mapping[str, Any]) -> dict[str, Any]:
        schema = command.argument_schema
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not isinstance(properties, Mapping):
            raise CatalogValidationError("invalid_argument_schema", "properties must be an object.")
        unknown = set(args) - set(properties)
        if unknown or (set(args) - set(properties)):
            name = sorted(unknown)[0] if unknown else ""
            raise CatalogValidationError(
                "unknown_argument", f"Unknown argument {name!r}.", path=name
            )
        missing = required - set(args)
        if missing:
            name = sorted(missing)[0]
            raise CatalogValidationError(
                "missing_argument", f"Missing required argument {name!r}.", path=name
            )
        result = dict(args)
        for name, definition in properties.items():
            if name not in result and isinstance(definition, Mapping) and "default" in definition:
                result[name] = definition["default"]
        for name, value in result.items():
            definition = properties.get(name)
            if not isinstance(definition, Mapping):
                raise CatalogValidationError(
                    "invalid_argument_schema", f"Invalid schema for {name!r}."
                )
            expected = definition.get("type")
            valid = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
                "array": isinstance(value, list),
                "object": isinstance(value, Mapping),
            }.get(str(expected), True)
            if not valid:
                raise CatalogValidationError(
                    "wrong_type", f"Argument {name!r} must have type {expected!r}.", path=name
                )
            if isinstance(value, str) and _UNSAFE_ARGUMENTS.search(value):
                raise CatalogValidationError(
                    "unsafe_argument",
                    f"Argument {name!r} contains shell control characters.",
                    path=name,
                )
            if "enum" in definition and value not in definition["enum"]:
                raise CatalogValidationError(
                    "invalid_value", f"Argument {name!r} is not allowed.", path=name
                )
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in definition and value < definition["minimum"]:
                    raise CatalogValidationError(
                        "out_of_range", f"Argument {name!r} violates minimum.", path=name
                    )
                if "maximum" in definition and value > definition["maximum"]:
                    raise CatalogValidationError(
                        "out_of_range", f"Argument {name!r} violates maximum.", path=name
                    )
        return result

    def validate_command(
        self,
        command_id: str,
        args: Mapping[str, Any],
        *,
        tenant_id: str | None = None,
        preconditions: Mapping[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Validate identity, tenant, typed arguments, placeholders, and preconditions."""
        command = self.command(command_id)
        if tenant_id is not None and command.tenant_scope not in (None, "*", tenant_id):
            raise CatalogValidationError("tenant_scope", "Command is not scoped to this tenant.")
        provided = preconditions or {}
        missing = [name for name in command.preconditions if not provided.get(name, False)]
        if missing:
            raise CatalogValidationError(
                "preconditions_not_met", f"Preconditions not met: {missing}."
            )
        args_dict = self._check_schema(command, args)
        self._check_template(command, args_dict)
        return args_dict

    def render(
        self,
        command_id: str,
        args: Mapping[str, Any],
        *,
        tenant_id: str | None = None,
        preconditions: Mapping[str, bool] | None = None,
    ) -> list[str]:
        """Render a validated command as an argv list, never as shell text."""
        command = self.command(command_id)
        valid = self.validate_command(
            command_id, args, tenant_id=tenant_id, preconditions=preconditions
        )
        return [part.format(**valid) for part in command.template]

    def validate_links(self) -> None:
        """Ensure rollback references exist and remain in the same tenant scope."""
        ids = {command.id for command in self.commands}
        for command in self.commands:
            if command.rollback_command_id and command.rollback_command_id not in ids:
                raise CatalogValidationError(
                    "rollback_missing",
                    f"Rollback command {command.rollback_command_id!r} is not in the catalog.",
                )
            if command.rollback_command_id:
                rollback = self.command(command.rollback_command_id)
                if rollback.tenant_scope not in (None, "*", command.tenant_scope, self.tenant_id):
                    raise CatalogValidationError(
                        "rollback_scope", "Rollback command has a different tenant scope."
                    )

    def build_registry(
        self,
        executor: Callable[[CommandSpec, list[str], dict[str, Any]], Any],
        *,
        registry: ToolRegistry | None = None,
    ) -> ToolRegistry:
        """Expose only catalog commands through the existing ToolRegistry."""
        target = registry or ToolRegistry()
        for command in self.commands:
            input_model = _input_model(command)

            tool = Tool(
                name=command.id,
                description=command.description,
                input_model=input_model,
                callable=_CatalogInvoker(self, command.id, executor),
                risk=command.risk_tier,
                idempotent=command.risk_tier == "read",
                metadata={"catalog_version": self.version, "tenant_id": self.tenant_id},
            )
            target.register(tool)
        return target


@dataclass(frozen=True)
class _CatalogInvoker:
    """Picklable callable that binds one catalog command to a backend executor."""

    catalog: CommandCatalog
    command_id: str
    executor: Callable[[CommandSpec, list[str], dict[str, Any]], Any]

    def __call__(self, **kwargs: Any) -> Any:
        command = self.catalog.command(self.command_id)
        argv = self.catalog.render(self.command_id, kwargs, tenant_id=self.catalog.tenant_id)
        return self.executor(command, argv, dict(kwargs))


def _catalog_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyYAML is required for YAML command catalogs.") from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise CatalogValidationError("invalid_catalog", "Catalog root must be an object.")
    return data


def load_catalog(path: str | Path) -> CommandCatalog:
    """Load and validate a JSON or YAML command catalog."""
    catalog = CommandCatalog.model_validate(_catalog_data(Path(path)))
    catalog.validate_links()
    return catalog


def draft_from_sop(sop: SopDoc, *, version: str = "draft-1") -> CatalogDraft:
    """Generate an unapproved catalog draft from SOP command references."""
    commands: dict[str, CommandSpec] = {}
    step_ids: list[str] = []
    for step in sop.steps:
        command = step.action
        step_ids.append(str(step.i))
        commands.setdefault(
            command.id,
            command.model_copy(update={"tenant_id": sop.tenant_id, "tenant_scope": sop.tenant_id}),
        )
    return CatalogDraft(
        tenant_id=sop.tenant_id,
        version=version,
        commands=tuple(commands.values()),
        source_step_ids=tuple(step_ids),
    )
