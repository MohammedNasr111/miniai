"""Offline: automatic memory recall injects relevant facts, skips unrelated."""

from __future__ import annotations

from tests.support import use_temp_data

use_temp_data()

from memory.database.db import save_memory
from memory.recall import (
    MEMORY_HEADER,
    format_memory_block,
    recall_relevant,
)
from llm.base import ChatMessage
from scripts.chat import ChatSession, run_user_turn
from unittest.mock import MagicMock, patch

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    save_memory("The user's favorite color is teal.", "preference")
    save_memory("Project MiniAI uses a local Lemonade model.", "project")

    # Relevant query — no embeddings required for offline determinism
    hits = recall_relevant(
        "What's my favourite colour?",
        use_embeddings=False,
    )
    _check(
        "relevant_hit",
        any("teal" in (h.get("content") or "").lower() for h in hits),
        repr(hits),
    )
    block = format_memory_block(hits)
    _check(
        "block_format",
        MEMORY_HEADER in block and "teal" in block.lower(),
        block[:200],
    )

    # Unrelated query should inject nothing above threshold
    cold = recall_relevant(
        "What is the weather in Kuala Lumpur today?",
        use_embeddings=False,
    )
    _check("unrelated_empty", cold == [], repr(cold))

    # Fresh session: injected system block present before model call
    provider = MagicMock()

    class _Resp:
        content = "Your favourite colour is teal."
        tool_calls = None
        check_meta = None

    provider.chat = MagicMock(return_value=_Resp())
    # Bypass lemonade; stub run_tool_rounds to inspect history
    captured: dict = {}

    def _fake_rounds(provider, history, guard, transcript=None, **kwargs):
        captured["history"] = list(history)
        return _Resp()

    session = ChatSession(
        provider=provider,
        history=[ChatMessage(role="system", content="sys")],
        guard=MagicMock(),
        transcript=None,
        turn_count=0,
        last_prompt_tokens=None,
    )
    with patch("scripts.chat.run_tool_rounds", side_effect=_fake_rounds):
        with patch("scripts.chat.remember_urls_from_text"):
            ans = run_user_turn(session, "What's my favourite colour?")
    hist = captured.get("history") or []
    sys_blocks = [
        m.content
        for m in hist
        if getattr(m, "role", None) == "system" and MEMORY_HEADER in (m.content or "")
    ]
    _check(
        "injected_in_fresh_session",
        bool(sys_blocks) and "teal" in sys_blocks[0].lower(),
        f"n={len(sys_blocks)} ans={ans!r}",
    )

    # Unrelated turn: no memory system block
    captured.clear()
    session2 = ChatSession(
        provider=provider,
        history=[ChatMessage(role="system", content="sys")],
        guard=MagicMock(),
        transcript=None,
        turn_count=0,
        last_prompt_tokens=None,
    )
    with patch("scripts.chat.run_tool_rounds", side_effect=_fake_rounds):
        with patch("scripts.chat.remember_urls_from_text"):
            run_user_turn(session2, "What is the weather in Kuala Lumpur today?")
    hist2 = captured.get("history") or []
    sys_blocks2 = [
        m.content
        for m in hist2
        if getattr(m, "role", None) == "system" and MEMORY_HEADER in (m.content or "")
    ]
    _check("unrelated_not_injected", sys_blocks2 == [], repr(sys_blocks2))

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
