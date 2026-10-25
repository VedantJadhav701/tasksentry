"""Unit tests for the tracked_client OpenAI wrapper integration."""

from typing import Any

from tasksentry.budget.budget import budget
from tasksentry.integrations.openai import tracked_client


def test_tracked_client_with_ambient_budget() -> None:
    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello from mock endpoint!",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            },
            "model": "gpt-4o-mini",
        }

    client = tracked_client(
        base_url="http://127.0.0.1:8000/v1",
        api_key="optional",
        model="gpt-4o-mini",
        transport=mock_transport,
    )

    with budget(task_id="tracked-run", max_tokens=10_000, max_cost_usd=1.0) as ctx:
        resp = client.chat.completions.create(messages=[{"role": "user", "content": "Hello"}])

        assert resp.content == "Hello from mock endpoint!"
        assert resp.usage.prompt_tokens == 100
        assert resp.usage.completion_tokens == 50

        # Ambient budget tracked tokens and calls
        assert ctx.budget.total_tokens == 150
        assert ctx.budget.llm_calls == 1
        assert ctx.budget.cost_usd > 0.0


def test_tracked_client_standalone() -> None:
    def mock_transport(
        url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Standalone response",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }

    client = tracked_client(transport=mock_transport)
    # Works normally when no budget context is entered
    resp = client.chat.completions.create(messages=[{"role": "user", "content": "Hi"}])
    assert resp.content == "Standalone response"
    assert resp.usage.total_tokens == 30
