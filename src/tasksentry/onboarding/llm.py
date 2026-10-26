"""Optional LLM bridge to Ollama (local or cloud-hosted models such as beam:cloud). stdlib only."""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable


def ollama_llm(
    model: str = "beam:cloud", base_url: str | None = None, timeout: float = 120.0
) -> Callable[[str], str]:
    base = (base_url or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    if not base.startswith("http"):
        base = "http://" + base

    def call(prompt: str) -> str:
        body = json.dumps(
            {
                "model": model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0},
            }
        ).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "TaskSentry/0.2"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(f"{base}/api/chat", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str(json.loads(resp.read().decode())["message"]["content"])

    return call
