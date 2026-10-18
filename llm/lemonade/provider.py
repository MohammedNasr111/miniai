"""Lemonade Server provider — talks to the local OpenAI-compatible API."""

from typing import Any, Optional

import requests

from config import settings
from llm.base import ChatMessage, ChatResponse, LLMProvider


class LemonadeProvider(LLMProvider):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        enable_thinking: bool | None = None,
        timeout: int | None = None,
    ) -> None:
        # Read settings at init time so MINIAI_MODEL / env overrides apply.
        self.base_url = (base_url or settings.LEMONADE_BASE_URL).rstrip("/")
        self.model = model if model is not None else settings.LEMONADE_MODEL
        self.enable_thinking = (
            enable_thinking
            if enable_thinking is not None
            else settings.ENABLE_THINKING_DEFAULT
        )
        self.timeout = (
            timeout if timeout is not None else settings.LEMONADE_TIMEOUT_SECONDS
        )

    def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        enable_thinking = kwargs.pop("enable_thinking", self.enable_thinking)
        timeout = kwargs.pop("timeout", self.timeout)
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
            timeout=timeout,
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
