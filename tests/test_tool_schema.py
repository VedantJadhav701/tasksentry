"""Unit tests for tool schema generation and argument validation."""

import pytest
from pydantic import BaseModel, Field

from tasksentry.exceptions import ToolValidationError
from tasksentry.tools.schema import (
    build_input_model_from_callable,
    generate_json_schema,
    validate_tool_arguments,
)


class UserProfile(BaseModel):
    username: str
    age: int = Field(gt=0)
    email: str | None = None


def test_valid_arguments() -> None:
    raw = {"username": "alice", "age": 30, "email": "alice@example.com"}
    validated = validate_tool_arguments(UserProfile, raw, tool_name="profile")
    assert validated["username"] == "alice"
    assert validated["age"] == 30
    assert validated["email"] == "alice@example.com"


def test_missing_required_field() -> None:
    # Missing username and age
    raw = {"email": "bob@example.com"}
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_arguments(UserProfile, raw, tool_name="profile")

    err = exc_info.value
    assert len(err.errors) >= 1
    assert any("username" in str(e) for e in err.errors)


def test_wrong_type_rejected() -> None:
    # Age cannot be string that doesn't parse or violates gt=0
    raw = {"username": "charlie", "age": -5}
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_arguments(UserProfile, raw, tool_name="profile")

    err = exc_info.value
    assert len(err.errors) >= 1
    assert any("age" in str(e) for e in err.errors)


def test_structured_error_content() -> None:
    raw = {"age": "not-an-int"}
    with pytest.raises(ToolValidationError) as exc_info:
        validate_tool_arguments(UserProfile, raw, tool_name="profile")

    err = exc_info.value
    assert isinstance(err.errors, list)
    assert len(err.errors) > 0
    first_err = err.errors[0]
    assert "loc" in first_err
    assert "msg" in first_err
    assert "type" in first_err


def test_dynamic_model_generation() -> None:
    def sample_func(path: str, count: int = 1) -> str:
        return path * count

    model = build_input_model_from_callable(sample_func, "SampleModel")
    schema = generate_json_schema(model)
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "count" in schema["properties"]
    assert schema["properties"]["count"]["default"] == 1
