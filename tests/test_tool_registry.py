"""Unit tests for ToolRegistry and @tool decorator."""

import pytest
from pydantic import BaseModel

from tasksentry.exceptions import ToolRegistrationError
from tasksentry.tools.registry import Tool, ToolRegistry, tool


def test_tool_decorator_and_registration() -> None:
    registry = ToolRegistry()

    @tool(
        name="test_echo",
        description="Echoes back a string",
        risk="read",
        timeout_seconds=5.0,
        idempotent=True,
        registry=registry,
    )
    def my_echo(message: str) -> str:
        return message

    assert registry.has("test_echo")
    t = registry.get("test_echo")
    assert t is not None
    assert t.name == "test_echo"
    assert t.description == "Echoes back a string"
    assert t.risk == "read"
    assert t.timeout_seconds == 5.0
    assert t.idempotent is True
    assert t(message="hello") == "hello"


def test_duplicate_registration_rejection() -> None:
    registry = ToolRegistry()

    def dummy_func(x: int) -> int:
        return x

    t1 = Tool(name="duplicate_tool", input_model=BaseModel, callable=dummy_func)
    t2 = Tool(name="duplicate_tool", input_model=BaseModel, callable=dummy_func)

    registry.register(t1)
    with pytest.raises(ToolRegistrationError):
        registry.register(t2)


def test_tool_lookup_and_missing() -> None:
    registry = ToolRegistry()

    def dummy() -> str:
        return "ok"

    t = Tool(name="lookup_tool", input_model=BaseModel, callable=dummy)
    registry.register(t)

    assert registry.get("lookup_tool") is t
    assert registry["lookup_tool"] is t
    assert registry.get("unknown_tool") is None

    with pytest.raises(KeyError):
        _ = registry["unknown_tool"]


def test_allowlist_filtering() -> None:
    registry = ToolRegistry()

    def dummy() -> str:
        return "ok"

    t1 = Tool(name="tool_a", input_model=BaseModel, callable=dummy)
    t2 = Tool(name="tool_b", input_model=BaseModel, callable=dummy)
    registry.register(t1)
    registry.register(t2)

    # None allowlist allows everything
    assert registry.is_allowed("tool_a", None)
    assert registry.is_allowed("tool_b", None)

    # Explicit allowlist
    allowed = ("tool_a",)
    assert registry.is_allowed("tool_a", allowed)
    assert not registry.is_allowed("tool_b", allowed)


def test_schema_generation_from_pydantic() -> None:
    class CustomInput(BaseModel):
        query: str
        limit: int = 10

    registry = ToolRegistry()

    @tool(name="search", input_model=CustomInput, registry=registry)
    def search(query: str, limit: int = 10) -> list[str]:
        return [query] * limit

    t = registry["search"]
    schema = t.input_schema
    assert schema["type"] == "object"
    assert "query" in schema["properties"]
    assert "limit" in schema["properties"]
    assert "query" in schema.get("required", [])
