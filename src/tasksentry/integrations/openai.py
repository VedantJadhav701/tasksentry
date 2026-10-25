"""OpenAI-compatible tracked client integrating ambient budget accounting."""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from tasksentry.budget.budget import get_current_budget
from tasksentry.budget.pricing import calculate_cost
from tasksentry.models.base import ModelClient
from tasksentry.models.fake_model import FakeModel
from tasksentry.models.openai_compat import OpenAICompatibleClient


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class UsageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = "cmpl_tracked"
    choices: list[ChatChoice] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    model: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def content(self) -> str | None:
        if self.choices:
            return self.choices[0].message.content
        return None


class ChatCompletionsAPI:
    """Namespace mirroring OpenAI's client.chat.completions."""

    def __init__(
        self,
        client: ModelClient,
        default_model: str,
    ) -> None:
        self._client = client
        self._default_model = default_model

    def create(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatCompletionResponse:
        """Issue chat completion and track usage against active ambient budget."""
        target_model = model or self._default_model
        resp = self._client.complete(messages=messages, tools=tools, model=target_model, **kwargs)

        # Calculate cost
        try:
            cost_est = calculate_cost(
                model=target_model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
            )
            cost_usd = cost_est.total_cost
        except Exception:
            cost_usd = 0.0

        # Ambient budget tracking
        active_ctx = get_current_budget()
        if active_ctx is not None:
            active_ctx.record_usage(
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                cost_usd=cost_usd,
                model=target_model,
            )

        message = ChatMessage(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls,
        )
        choice = ChatChoice(
            index=0,
            message=message,
            finish_reason=resp.finish_reason,
        )
        usage = UsageInfo(
            prompt_tokens=resp.input_tokens,
            completion_tokens=resp.output_tokens,
            total_tokens=resp.input_tokens + resp.output_tokens,
        )

        return ChatCompletionResponse(
            choices=[choice],
            usage=usage,
            model=target_model,
            raw=resp.raw_response,
        )


class ChatAPI:
    """Namespace mirroring OpenAI's client.chat."""

    def __init__(self, client: ModelClient, default_model: str) -> None:
        self.completions = ChatCompletionsAPI(client, default_model)


class TrackedOpenAIClient:
    """Tracked OpenAI-compatible client wrapper."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        api_key: str | None = None,
        model: str = "fake-model",
        timeout: float = 60.0,
        transport: Callable[[str, dict[str, str], bytes, float], dict[str, Any]] | None = None,
        model_client: ModelClient | None = None,
    ) -> None:
        is_fake = (
            model in ("fake-model", "fake_model")
            and transport is None
            and not base_url.startswith("http")
        )
        if model_client is not None:
            self._underlying = model_client
        elif is_fake:
            self._underlying = FakeModel(model_name=model)
        else:
            self._underlying = OpenAICompatibleClient(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout=timeout,
                transport=transport,
            )
        self.chat = ChatAPI(self._underlying, default_model=model)


def tracked_client(
    base_url: str = "http://127.0.0.1:8000/v1",
    api_key: str | None = None,
    model: str = "fake-model",
    timeout: float = 60.0,
    transport: Callable[[str, dict[str, str], bytes, float], dict[str, Any]] | None = None,
    model_client: ModelClient | None = None,
) -> TrackedOpenAIClient:
    """Factory creating an OpenAI-compatible client tracked by TaskSentry."""
    return TrackedOpenAIClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        transport=transport,
        model_client=model_client,
    )
