"""Tool registration, discovery, metadata, and @tool decorator."""

import functools
from collections.abc import Callable, Iterable, Mapping
from typing import Any, overload

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.exceptions import ToolRegistrationError
from tasksentry.tools.schema import (
    build_input_model_from_callable,
    generate_json_schema,
    validate_tool_arguments,
)


class Tool(BaseModel):
    """Encapsulation of an executable agent tool with metadata and schemas."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    name: str
    description: str = ""
    input_model: type[BaseModel]
    output_model: type[BaseModel] | type[Any] | None = None
    output_schema: dict[str, Any] | None = None
    callable: Callable[..., Any]
    risk: str = "read"
    timeout_seconds: float | None = None
    idempotent: bool = False
    retry_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the underlying callable directly."""
        return self.callable(*args, **kwargs)

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema representation of the tool's input model."""
        return generate_json_schema(self.input_model)

    def validate_args(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Validate input arguments against the tool's input schema."""
        return validate_tool_arguments(self.input_model, arguments, tool_name=self.name)


class ToolRegistry:
    """Registry maintaining unique tools, schema lookup, and allowlists."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        """Register a new tool.

        Raises:
            ToolRegistrationError: if a tool with the same name already exists.
        """
        if tool.name in self._tools:
            raise ToolRegistrationError(f"Tool with name {tool.name!r} is already registered.")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        """Retrieve tool by name, or None if not found."""
        return self._tools.get(name)

    def __getitem__(self, name: str) -> Tool:
        """Retrieve tool by name, raising KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool {name!r} not found in registry.")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check whether a tool exists in the registry."""
        return name in self._tools

    def list_tools(self) -> list[Tool]:
        """Return list of all registered tools."""
        return list(self._tools.values())

    def names(self) -> list[str]:
        """Return names of all registered tools."""
        return sorted(self._tools.keys())

    def is_allowed(self, name: str, allowlist: Iterable[str] | None = None) -> bool:
        """Check whether tool name is permitted by an allowlist.

        If allowlist is None, every tool is allowed.
        """
        if allowlist is None:
            return True
        return name in set(allowlist)


# Global default registry for convenient imports
default_registry = ToolRegistry()


@overload
def tool(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    description: str | None = None,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | type[Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    risk: str = "read",
    timeout_seconds: float | None = None,
    idempotent: bool = False,
    retry_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> Tool: ...


@overload
def tool(
    func: None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | type[Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    risk: str = "read",
    timeout_seconds: float | None = None,
    idempotent: bool = False,
    retry_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> Callable[[Callable[..., Any]], Tool]: ...


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    input_model: type[BaseModel] | None = None,
    output_model: type[BaseModel] | type[Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    risk: str = "read",
    timeout_seconds: float | None = None,
    idempotent: bool = False,
    retry_policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    registry: ToolRegistry | None = None,
) -> Any:
    """Decorator to declare a tool with schema, risk, timeout, and metadata.

    Can be used as:
        @tool
        def my_tool(...): ...

        or

        @tool(name="read_file", risk="read", timeout_seconds=10, idempotent=True)
        def read_file(...): ...
    """

    def decorator(fn: Callable[..., Any]) -> Tool:
        tool_name = name or fn.__name__
        tool_desc = description or fn.__doc__ or ""
        in_model = input_model or build_input_model_from_callable(fn, f"{tool_name}_Input")

        tool_obj = Tool(
            name=tool_name,
            description=tool_desc.strip(),
            input_model=in_model,
            output_model=output_model,
            output_schema=output_schema,
            callable=fn,
            risk=risk,
            timeout_seconds=timeout_seconds,
            idempotent=idempotent,
            retry_policy=retry_policy,
            metadata=metadata or {},
        )

        functools.update_wrapper(tool_obj, fn)

        reg = registry if registry is not None else default_registry
        reg.register(tool_obj)
        return tool_obj

    if func is not None:
        return decorator(func)
    return decorator
