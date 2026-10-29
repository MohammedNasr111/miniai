"""Per-turn user text visible to filesystem tools (folder vs file routing)."""

from __future__ import annotations

_last_user_text: str = ""


def set_turn_user_text(text: str) -> None:
    global _last_user_text
    _last_user_text = text or ""
    try:
        from agent.data_cards import reset_listing_card_turn

        reset_listing_card_turn()
    except Exception:
        pass


def get_turn_user_text() -> str:
    return _last_user_text


def clear_turn_user_text() -> None:
    global _last_user_text
    _last_user_text = ""
    try:
        from agent.data_cards import reset_listing_card_turn

        reset_listing_card_turn()
    except Exception:
        pass
