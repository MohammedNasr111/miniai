"""Per-turn user text visible to filesystem tools (folder vs file routing)."""

from __future__ import annotations

_last_user_text: str = ""


def set_turn_user_text(text: str) -> None:
    global _last_user_text
    _last_user_text = text or ""


def get_turn_user_text() -> str:
    return _last_user_text


def clear_turn_user_text() -> None:
    global _last_user_text
    _last_user_text = ""
