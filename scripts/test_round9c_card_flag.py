"""Offline: card flag reset + early-abort turn scope (Round 9C/9D).

Round 9D: no card prompt sentence / strip — answer text left to honesty only.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


class _FakeTx:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: list[dict[str, Any]] = []

    def llm_call(self, **fields: Any) -> None:
        self.events.append(dict(fields))


class _FakeStreamProvider:
    def __init__(self, first_events: list, second_content: str = "Thoughtful.") -> None:
        self.first_events = list(first_events)
        self.second_content = second_content
        self.timeout = 30
        self.calls: list[dict[str, Any]] = []
        self._pass = 0

    def chat(self, messages, tools=None, **kwargs: Any):
        return self.chat_stream(messages, tools=tools, **kwargs)

    def chat_stream(
        self,
        messages,
        tools=None,
        *,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool_delta: Optional[Callable[[], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        **kwargs: Any,
    ):
        from llm.base import ChatResponse
        from llm.lemonade.provider import StreamCancelled

        enable_thinking = bool(kwargs.get("enable_thinking", False))
        self.calls.append({"enable_thinking": enable_thinking})
        self._pass += 1
        if enable_thinking or self._pass > 1:
            if on_token:
                on_token(self.second_content)
            return ChatResponse(
                content=self.second_content,
                finish_reason="stop",
                tool_calls=None,
                raw={},
            )
        content_parts: list[str] = []
        tool_calls = None
        for kind, payload in self.first_events:
            if cancel_check is not None and cancel_check():
                raise StreamCancelled("".join(content_parts))
            if kind == "content":
                content_parts.append(payload)
                if on_token:
                    on_token(payload)
            elif kind == "tool":
                if on_tool_delta:
                    on_tool_delta()
                tool_calls = [payload]
        if cancel_check is not None and cancel_check():
            raise StreamCancelled("".join(content_parts))
        return ChatResponse(
            content="".join(content_parts),
            finish_reason="tool_calls" if tool_calls else "stop",
            tool_calls=tool_calls,
            raw={},
        )


def main() -> int:
    from agent.data_cards import (
        build_data_card,
        listing_card_shown_this_turn,
        note_listing_card_shown,
        reset_listing_card_turn,
    )
    from agent.listing_honesty import maybe_correct_listing_answer
    from config import settings
    from llm.base import ChatMessage
    from scripts.agent_loop import _call_model, _history_for_model, _messages_after_latest_user

    reset_listing_card_turn()
    sys_msg = "You are MiniAI. Fixed system prompt."
    listing = [
        {"name": "alpha.txt", "type": "file", "size_bytes": 10, "size": "10 B"},
        {"name": "beta.txt", "type": "file", "size_bytes": 20, "size": "20 B"},
        {"name": "gamma.txt", "type": "file", "size_bytes": 30, "size": "30 B"},
    ]
    card = build_data_card(
        "list_directory",
        json.dumps(listing),
        question="List the files in C:\\tmp",
        args={"path": r"C:\tmp"},
    )
    check("card_built", card is not None)

    hist1 = [
        ChatMessage(role="system", content=sys_msg),
        ChatMessage(role="user", content="List the files in C:\\tmp"),
    ]
    msg0_before = hist1[0].content
    note_listing_card_shown(card)
    payload1 = _history_for_model(hist1)
    check(
        "turn1_msg0_byte_identical",
        payload1[0].content == msg0_before == sys_msg,
        repr(payload1[0].content)[:80],
    )

    reset_listing_card_turn()
    check("flag_false_at_turn2_start", not listing_card_shown_this_turn())
    hist2 = [
        ChatMessage(role="system", content=sys_msg),
        ChatMessage(role="user", content="List the files in C:\\tmp"),
        ChatMessage(role="assistant", content="Listed above."),
        ChatMessage(
            role="user",
            content="Write a Python function that counts words in eval_wordcount.",
        ),
    ]
    payload2 = _history_for_model(hist2)
    check(
        "turn2_msg0_byte_identical_to_turn1",
        payload2[0].content == msg0_before,
        repr(payload2[0].content)[:80],
    )

    note_listing_card_shown(card)
    reset_listing_card_turn()
    check("eval_flag_false_after_task_reset", not listing_card_shown_this_turn())

    # List + card: honesty leaves correct names; no strip path empties them.
    td = Path(tempfile.mkdtemp(prefix="miniai_r9d_"))
    tx = td / "t.jsonl"
    tx.write_text(
        json.dumps({"type": "user_turn", "user_prompt": "List the files"})
        + "\n"
        + json.dumps(
            {
                "type": "tool_call",
                "name": "list_directory",
                "args": {"path": r"C:\tmp", "sort_by": "name"},
                "result": json.dumps(listing),
                "outcome": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    good = (
        "Here are the files:\n"
        "1. `alpha.txt`\n"
        "2. `beta.txt`\n"
        "3. `gamma.txt`\n"
    )
    reset_listing_card_turn()
    note_listing_card_shown(card)
    after_honesty, hmeta = maybe_correct_listing_answer(
        "List the files in C:\\tmp",
        good,
        transcript=_FakeTx(tx),
    )
    check(
        "honesty_no_correct_when_names_ok",
        hmeta is None and after_honesty == good,
        str(hmeta),
    )
    check("answer_keeps_names", "alpha.txt" in after_honesty and "gamma.txt" in after_honesty)
    check(
        "no_removed_note",
        "Removed" not in after_honesty,
        after_honesty,
    )

    # Early-abort: prior-turn tool result must NOT enable abort
    long_text = "A" * 30
    events = [
        ("content", chunk)
        for chunk in [long_text[:10], long_text[10:20], long_text[20:]]
    ]
    prior_tool_hist = [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(role="user", content="List files please."),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "old",
                    "type": "function",
                    "function": {"name": "list_directory", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(
            role="tool",
            content="[]",
            tool_call_id="old",
            name="list_directory",
        ),
        ChatMessage(role="assistant", content="Done listing."),
        ChatMessage(role="user", content="Why is the sky blue? Explain carefully."),
    ]
    cur = _messages_after_latest_user(prior_tool_hist)
    check(
        "scope_excludes_prior_tools",
        not any(getattr(m, "role", None) == "tool" for m in cur),
        str([getattr(m, "role", None) for m in cur]),
    )
    prov = _FakeStreamProvider(events, second_content="Sky is blue from Rayleigh.")
    tx_ea = _FakeTx(td / "ea.jsonl")
    patches = [
        patch.object(settings, "THINKING_POLICY", "smart"),
        patch.object(settings, "EARLY_ABORT", True),
        patch(
            "scripts.agent_loop.compress_cross_turn_history",
            lambda h, tools=None: None,
        ),
        patch("scripts.agent_loop.compress_browser_history", lambda h: None),
        patch(
            "scripts.agent_loop.enforce_context_budget",
            lambda h, tools=None: None,
        ),
        patch("scripts.agent_loop.active_tool_schemas", lambda: []),
        patch(
            "scripts.agent_loop.first_pass_timeout_seconds", lambda h, t: 30
        ),
        patch("agent.perf_probe.snapshot_before_call", lambda: {}),
        patch("agent.perf_probe.enrich_llm_fields", lambda **kw: {}),
    ]
    for p in patches:
        p.start()
    try:
        resp = _call_model(
            prov,
            prior_tool_hist,
            transcript=tx_ea,
            on_stream_delta=lambda _t: None,
            on_stream_clear=lambda: None,
        )
    finally:
        for p in reversed(patches):
            p.stop()
    check(
        "prior_tool_no_early_abort",
        not any(e.get("early_abort") for e in tx_ea.events),
        str(tx_ea.events),
    )
    check(
        "prior_tool_still_answers",
        "Sky is blue" in (resp.content or ""),
        repr(resp.content),
    )

    if FAILURES:
        print(f"\n{FAILURES} failure(s)")
        return 1
    print("\nAll round9c_card_flag tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
