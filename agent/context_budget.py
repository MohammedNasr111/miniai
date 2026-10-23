"""Prompt size estimates and in-place history shrinking for Lemonade ctx."""

from __future__ import annotations

import json
from typing import Any, Optional

CONTEXT_LIMIT_TOKENS = 16_384
ANSWER_RESERVE_TOKENS = 2_048
CONTEXT_BUDGET_TOKENS = CONTEXT_LIMIT_TOKENS - ANSWER_RESERVE_TOKENS
CHARS_PER_TOKEN = 3.5
TOOL_RESULT_MAX_CHARS = 12_000
TRIM_MARKER = "\n[trimmed to fit]\n"


def estimate_tokens(text: Optional[str]) -> float:
    return len(text or "") / CHARS_PER_TOKEN


def estimate_message_tokens(message: Any) -> float:
    total = estimate_tokens(getattr(message, "content", None) or "")
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        try:
            total += estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
        except (TypeError, ValueError):
            total += estimate_tokens(str(tool_calls))
    return total


def estimate_prompt_tokens(history: list, tools: Optional[list] = None) -> float:
    total = sum(estimate_message_tokens(m) for m in history)
    if tools:
        try:
            total += estimate_tokens(json.dumps(tools, ensure_ascii=False))
        except (TypeError, ValueError):
            total += estimate_tokens(str(tools))
    return total


def trim_head_tail(text: str, max_chars: int, marker: str = TRIM_MARKER) -> str:
    if max_chars <= 0:
        return marker.strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker) + 2:
        return text[:max_chars]
    keep = max_chars - len(marker)
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + text[-tail:]


def cap_tool_result_text(text: str, max_chars: int = TOOL_RESULT_MAX_CHARS) -> str:
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    return trim_head_tail(text, max_chars)


def _latest_user_index(history: list) -> int:
    for index in range(len(history) - 1, -1, -1):
        if getattr(history[index], "role", None) == "user":
            return index
    return -1


def enforce_context_budget(
    history: list,
    tools: Optional[list] = None,
    budget_tokens: float = CONTEXT_BUDGET_TOKENS,
) -> None:
    """Shrink history in place so estimated prompt tokens stay under budget.

    Never modifies the system prompt or the latest user message. Shrinks the
    largest tool results first, then older messages.
    """
    if not history:
        return
    for message in history:
        if getattr(message, "role", None) == "tool" and isinstance(
            getattr(message, "content", None), str
        ):
            message.content = cap_tool_result_text(message.content)

    protected: set[int] = set()
    for index, message in enumerate(history):
        if getattr(message, "role", None) == "system":
            protected.add(index)
    latest_user = _latest_user_index(history)
    if latest_user >= 0:
        protected.add(latest_user)

    def _over() -> bool:
        return estimate_prompt_tokens(history, tools) > budget_tokens

    while _over():
        candidates = [
            (index, message)
            for index, message in enumerate(history)
            if index not in protected
            and getattr(message, "role", None) == "tool"
            and isinstance(getattr(message, "content", None), str)
            and len(message.content) > 64
        ]
        if not candidates:
            break
        _index, message = max(
            candidates, key=lambda item: len(item[1].content or "")
        )
        new_len = max(64, len(message.content) // 2)
        message.content = trim_head_tail(message.content, new_len)

    while _over():
        candidates = [
            (index, message)
            for index, message in enumerate(history)
            if index not in protected
            and isinstance(getattr(message, "content", None), str)
            and len(message.content) > 64
        ]
        if not candidates:
            break
        _index, message = max(
            candidates, key=lambda item: len(item[1].content or "")
        )
        new_len = max(64, len(message.content) // 2)
        message.content = trim_head_tail(message.content, new_len)
