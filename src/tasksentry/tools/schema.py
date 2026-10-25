"""JSON schema generation and argument validation for tools."""

import inspect
import warnings
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from tasksentry.exceptions import ToolValidationError


def build_input_model_from_callable(func: Any, model_name: str) -> type[BaseModel]:
    """Dynamically construct a Pydantic v2 input model from a callable's signature."""
    sig = inspect.signature(func)
    fields: dict[str, Any] = {}

    for param in sig.parameters.values():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue

        param_type: Any = (
            param.annotation if param.annotation is not inspect.Parameter.empty else Any
        )
        if param.default is not inspect.Parameter.empty:
            fields[param.name] = (param_type, param.default)
        else:
            fields[param.name] = (param_type, ...)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=UserWarning,
            message=r'.*shadows an attribute in parent "BaseModel".*',
        )
        return create_model(
            model_name,
            __config__=ConfigDict(protected_namespaces=()),
            **fields,
        )


def generate_json_schema(model: type[BaseModel] | None) -> dict[str, Any]:
    """Generate a standard JSON Schema from a Pydantic model."""
    if model is None:
        return {"type": "object", "properties": {}}
    return model.model_json_schema()


def validate_tool_arguments(
    input_model: type[BaseModel],
    arguments: Mapping[str, Any],
    tool_name: str = "tool",
) -> dict[str, Any]:
    """Validate argument dictionary against a Pydantic model.

    Returns:
        Clean, validated argument dictionary.

    Raises:
        ToolValidationError: if validation fails, containing structured error details.
    """
    if input_model is BaseModel:
        return dict(arguments)

    try:
        instance = input_model.model_validate(dict(arguments))
        result: dict[str, Any] = instance.model_dump()
        return result
    except Exception as exc:
        errors: list[dict[str, Any]] = []
        if hasattr(exc, "errors") and callable(exc.errors):
            errors = [dict(err) for err in exc.errors()]
        raise ToolValidationError(
            f"Argument validation failed for tool {tool_name!r}: {exc}",
            errors=errors,
        ) from exc
