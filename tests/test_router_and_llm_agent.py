"""Unit tests for SemanticModelRouter and LLMAgent."""

from typing import Any

from tasksentry.budget.budget import Budget
from tasksentry.core.state import CanonicalState
from tasksentry.harness.agent import LLMAgent
from tasksentry.models.base import ModelClient, ModelResponse
from tasksentry.models.router import SemanticModelRouter


class MockClient(ModelClient):
    """Deterministic mock client for testing routing and LLMAgent."""

    def __init__(self, name: str, responses: list[ModelResponse] | None = None) -> None:
        self.name = name
        self.responses = list(responses or [])
        self.call_history: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        self.call_history.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        if self.responses:
            return self.responses.pop(0)
        return ModelResponse(
            content="Task is complete.",
            model=self.name,
            input_tokens=10,
            output_tokens=5,
        )


def test_semantic_router_classification() -> None:
    router = SemanticModelRouter(
        routine_model="qwen2.5:3b",
        reasoning_model="qwen3:4b-instruct-2507-q4_K_M",
    )

    # Routine message
    routine_msgs = [{"role": "user", "content": "List files in the current folder."}]
    model, reason = router.classify_route(routine_msgs)
    assert model == "qwen2.5:3b"
    assert "routine" in reason

    # Reasoning message with keywords
    reasoning_msgs = [
        {"role": "user", "content": "Investigate root cause of failure and plan refactoring"}
    ]
    model, reason = router.classify_route(reasoning_msgs)
    assert model == "qwen3:4b-instruct-2507-q4_K_M"
    assert "semantic match" in reason

    # Context flags
    flag_model, _ = router.classify_route(routine_msgs, context={"is_replanning": True})
    assert flag_model == "qwen3:4b-instruct-2507-q4_K_M"

    flag_model2, _ = router.classify_route(routine_msgs, context={"loop_warning": True})
    assert flag_model2 == "qwen3:4b-instruct-2507-q4_K_M"


def test_semantic_router_fallback_and_completion() -> None:
    failing_client = MockClient("failing_model")

    def raise_err(*args: Any, **kwargs: Any) -> ModelResponse:
        raise ConnectionError("Ollama offline")

    failing_client.complete = raise_err  # type: ignore[method-assign]

    healthy_client = MockClient(
        "healthy_model",
        [ModelResponse(content="Recovered response", model="healthy_model")],
    )

    router = SemanticModelRouter(
        routine_model="healthy_model",
        reasoning_model="failing_model",
        fallback_models=["healthy_model"],
        clients={"failing_model": failing_client, "healthy_model": healthy_client},
    )

    # Trigger reasoning query which targets failing_model first, then falls back to healthy_model
    resp = router.complete(
        messages=[{"role": "user", "content": "Investigate why and plan architecture"}]
    )
    assert resp.content == "Recovered response"
    assert resp.model == "healthy_model"
    assert resp.raw_response.get("routed_model") == "healthy_model"


def test_llm_agent_native_tool_call() -> None:
    mock_resp = ModelResponse(
        content="",
        tool_calls=[
            {"name": "test_tool", "arguments": {"query": "hello"}},
        ],
        model="qwen2.5:3b",
        input_tokens=15,
        output_tokens=10,
    )
    client = MockClient("qwen2.5:3b", [mock_resp])
    agent = LLMAgent(model_client=client)

    state = CanonicalState(goal="Test goal")
    action = agent.step(state, [], {})

    assert action["type"] == "tool_call"
    assert action["tool"] == "test_tool"
    assert action["arguments"] == {"query": "hello"}


def test_llm_agent_markdown_json_tool_call() -> None:
    json_block = '```json\n{"tool": "read_file", "arguments": {"path": "a.txt"}}\n```'
    mock_resp = ModelResponse(
        content=f"I will read the file now.\n{json_block}",
        model="qwen2.5:3b",
        input_tokens=20,
        output_tokens=15,
    )
    client = MockClient("qwen2.5:3b", [mock_resp])
    agent = LLMAgent(model_client=client)

    state = CanonicalState(goal="Test markdown tool call")
    action = agent.step(state, [], {})

    assert action["type"] == "tool_call"
    assert action["tool"] == "read_file"
    assert action["arguments"] == {"path": "a.txt"}


def test_llm_agent_completion_and_budget_tracking() -> None:
    mock_resp = ModelResponse(
        content="COMPLETE: Done inspecting repository.",
        model="qwen2.5:3b",
        input_tokens=25,
        output_tokens=10,
    )
    client = MockClient("qwen2.5:3b", [mock_resp])
    budget = Budget(max_tokens=1000)

    agent = LLMAgent(model_client=client, budget=budget)
    state = CanonicalState(goal="Inspect repo")
    action = agent.step(state, [], {})

    assert action["type"] == "complete_task"
    assert "Done inspecting repository" in action["answer"]

    # Verify budget recorded tokens and calls
    assert budget.input_tokens == 25
    assert budget.output_tokens == 10
    assert budget.total_tokens == 35
    assert budget.llm_calls == 1
