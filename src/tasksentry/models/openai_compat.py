"""Client for OpenAI-compatible LLM endpoints (vLLM, Ollama, OpenAI, LocalAI)."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from tasksentry.exceptions import ModelError
from tasksentry.models.base import ModelClient, ModelResponse


def convert_tools_to_openai_format(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert tool specifications into OpenAI function-calling format."""
    if not tools:
        return []

    formatted: list[dict[str, Any]] = []
    for t in tools:
        if "type" in t and t.get("type") == "function" and "function" in t:
            formatted.append(t)
        else:
            name = t.get("name", "unnamed_tool")
            description = t.get("description", "")
            parameters = t.get("parameters") or t.get("input_schema") or {"type": "object"}
            formatted.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
    return formatted


class OpenAICompatibleClient(ModelClient):
    """Client for any OpenAI-compatible completions API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
        transport: Callable[[str, dict[str, str], bytes, float], dict[str, Any]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._transport = transport

    def _default_transport(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout: float,
    ) -> dict[str, Any]:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                resp_bytes = response.read()
                data = json.loads(resp_bytes.decode("utf-8"))
                return data if isinstance(data, dict) else {}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            raise ModelError(f"HTTP {exc.code} from {url}: {err_msg}") from exc
        except urllib.error.URLError as exc:
            raise ModelError(f"Network error connecting to {url}: {exc.reason}") from exc
        except Exception as exc:
            raise ModelError(f"Request failed: {exc}") from exc

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Send chat completion request to the OpenAI-compatible endpoint."""
        url = f"{self.base_url}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": kwargs.pop("model", self.model),
            "messages": messages,
            **kwargs,
        }
        if tools:
            payload["tools"] = convert_tools_to_openai_format(tools)

        body_bytes = json.dumps(payload).encode("utf-8")
        timeout = float(kwargs.get("timeout", self.timeout))

        transport_fn = self._transport or self._default_transport
        try:
            raw_data = transport_fn(url, headers, body_bytes, timeout)
        except ModelError:
            raise
        except Exception as exc:
            raise ModelError(f"Request failed: {exc}") from exc

        # Parse OpenAI format
        choices = raw_data.get("choices", [])
        if not choices:
            return ModelResponse(
                content=None,
                tool_calls=[],
                input_tokens=0,
                output_tokens=0,
                model=self.model,
                finish_reason="stop",
                raw_response=raw_data,
            )

        choice = choices[0]
        msg = choice.get("message", {})
        content = msg.get("content")
        finish_reason = choice.get("finish_reason", "stop")

        tool_calls: list[dict[str, Any]] = []
        raw_tool_calls = msg.get("tool_calls", [])
        for tc in raw_tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            if isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw)
                except Exception:
                    args = {"raw_arguments": args_raw}
            else:
                args = args_raw or {}
            tool_calls.append(
                {
                    "id": tc.get("id"),
                    "name": name,
                    "arguments": args,
                }
            )

        usage = raw_data.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=raw_data.get("model", self.model),
            finish_reason=finish_reason,
            raw_response=raw_data,
        )
