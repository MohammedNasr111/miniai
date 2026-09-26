"""Lemonade Server provider — talks to the local OpenAI-compatible API."""

from typing import Any, Optional

import requests

from config import settings
from llm.base import ChatMessage, ChatResponse, LLMProvider


class LemonadeProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = settings.LEMONADE_BASE_URL,
        model: str = settings.LEMONADE_MODEL,
        enable_thinking: bool = settings.ENABLE_THINKING_DEFAULT,
        timeout: int = settings.LEMONADE_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.enable_thinking = enable_thinking
        self.timeout = timeout

    def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        enable_thinking = kwargs.pop("enable_thinking", self.enable_thinking)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        choice = data["choices"][0]["message"]
        return ChatResponse(
            content=choice.get("content", ""),
            finish_reason=data["choices"][0].get("finish_reason"),
            tool_calls=choice.get("tool_calls"),
            raw=data,
        )
