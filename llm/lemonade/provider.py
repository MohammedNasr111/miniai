"""Lemonade Server provider — talks to the local OpenAI-compatible API."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

import requests

from config import settings
from llm.base import ChatMessage, ChatResponse, LLMProvider


class StreamCancelled(KeyboardInterrupt):
    """Raised when cancel_check fires mid-stream; carries partial text."""

    def __init__(self, partial: str = "") -> None:
        super().__init__()
        self.partial = partial or ""


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

    def _build_payload(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]],
        enable_thinking: bool,
        kwargs: dict[str, Any],
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
        payload.update(kwargs)
        return payload

    def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        enable_thinking = kwargs.pop("enable_thinking", self.enable_thinking)
        timeout = kwargs.pop("timeout", self.timeout)
        payload = self._build_payload(
            messages, tools, enable_thinking, kwargs, stream=False
        )
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        # Lemonade may omit charset; requests would otherwise treat text as ISO-8859-1.
        response.encoding = "utf-8"
        data = response.json()
        choice = data["choices"][0]["message"]
        return ChatResponse(
            content=choice.get("content", "") or "",
            finish_reason=data["choices"][0].get("finish_reason"),
            tool_calls=choice.get("tool_calls"),
            raw=data,
        )

    def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool_delta: Optional[Callable[[], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """OpenAI-compatible streaming chat. Calls on_token with each content delta.

        If cancel_check returns True mid-stream, raises StreamCancelled(partial).
        Tool-call deltas are accumulated; on_token is only fed content deltas.
        on_tool_delta (if set) is called once per chunk that carries any tool_calls.
        """
        enable_thinking = kwargs.pop("enable_thinking", self.enable_thinking)
        timeout = kwargs.pop("timeout", self.timeout)
        payload = self._build_payload(
            messages, tools, enable_thinking, kwargs, stream=True
        )
        content_parts: list[str] = []
        # tool_call index -> mutable dict being built
        tool_acc: dict[int, dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        raw_chunks: list[dict[str, Any]] = []

        with requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=timeout,
            stream=True,
        ) as response:
            response.raise_for_status()
            # Without charset, requests defaults to ISO-8859-1 and mojibakes UTF-8
            # (e.g. en-dash → â€"). Force UTF-8 before iter_lines(decode_unicode=True).
            response.encoding = "utf-8"
            for raw_line in response.iter_lines(decode_unicode=True):
                if cancel_check is not None and cancel_check():
                    raise StreamCancelled("".join(content_parts))
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                raw_chunks.append(chunk)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice0 = choices[0]
                fr = choice0.get("finish_reason")
                if fr:
                    finish_reason = fr
                delta = choice0.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    if on_token is not None:
                        on_token(piece)
                tc_deltas = delta.get("tool_calls") or []
                if tc_deltas and on_tool_delta is not None:
                    try:
                        on_tool_delta()
                    except Exception:
                        pass
                for tc in tc_deltas:
                    idx = tc.get("index", 0)
                    slot = tool_acc.setdefault(
                        idx,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    if tc.get("type"):
                        slot["type"] = tc["type"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = (
                            slot["function"].get("name") or ""
                        ) + fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] = (
                            slot["function"].get("arguments") or ""
                        ) + fn["arguments"]

        tool_calls: Optional[list[dict[str, Any]]] = None
        if tool_acc:
            tool_calls = [tool_acc[i] for i in sorted(tool_acc)]
        content = "".join(content_parts)
        # Pull usage/timings from the last stream chunk when the server sends them.
        usage: dict[str, Any] = {}
        timings: Optional[dict[str, Any]] = None
        for chunk in reversed(raw_chunks):
            if not isinstance(chunk, dict):
                continue
            if timings is None and isinstance(chunk.get("timings"), dict):
                timings = chunk["timings"]
            if not usage and isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            if timings is not None and usage:
                break
        raw: dict[str, Any] = {"stream_chunks": len(raw_chunks), "stream": True}
        if usage:
            raw["usage"] = usage
        if timings is not None:
            raw["timings"] = timings
        return ChatResponse(
            content=content,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            raw=raw,
        )
