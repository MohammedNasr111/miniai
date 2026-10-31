"""Round 13 Part 1 — Thinking… before Writing… for hide-draft + thinking pass."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.base import ChatMessage, ChatResponse

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


class _HideDraftThenThinkProvider:
    """First call = hidden draft (thinking off); second = thinking-on stream."""

    def __init__(self) -> None:
        self.n = 0
        self.timeout = 60
        self.enable_thinking = False

    def chat(self, messages, tools=None, **kwargs):
        return self.chat_stream(messages, tools=tools, **kwargs)

    def chat_stream(self, messages, tools=None, **kwargs):
        thinking = bool(kwargs.get("enable_thinking", False))
        on_token = kwargs.get("on_token")
        self.n += 1
        if not thinking:
            draft = "HIDDEN_DRAFT_TEXT " * 4
            if on_token is not None:
                on_token(draft)
            return ChatResponse(
                content=draft, finish_reason="stop", tool_calls=None, raw={}
            )
        final = "VISIBLE_FINAL_ANSWER"
        if on_token is not None:
            on_token(final)
        return ChatResponse(
            content=final, finish_reason="stop", tool_calls=None, raw={}
        )


def test_phase_priority_thinking_beats_working() -> None:
    from app.turn_phase import phase_from_turn

    p = phase_from_turn(thinking=True)
    _check("thinking_label", p["kind"] == "thinking" and p["label"] == "Thinking…", repr(p))
    p = phase_from_turn(writing=True, thinking=True)
    _check("writing_over_thinking", p["kind"] == "writing", repr(p))
    p = phase_from_turn(
        thinking=True,
        steps=[
            {
                "tool": "list_directory",
                "name": "Listing",
                "running": True,
                "args": {"path": r"C:\Users\james\Downloads"},
            }
        ],
    )
    _check("tool_over_thinking", p["kind"] == "tool" and "Downloads" in p["label"], repr(p))


def test_hide_draft_emits_thinking_before_writing() -> None:
    """Fake provider: Thinking… callback before any visible Writing… delta."""
    from scripts.agent_loop import _call_model

    prov = _HideDraftThenThinkProvider()
    events: list[str] = []

    def on_thinking() -> None:
        events.append("thinking")

    def on_delta(text: str) -> None:
        if text:
            events.append("writing:" + text[:40])

    hist = [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(
            role="user",
            content="In about 120 words, explain what a page fault is.",
        ),
    ]
    with patch("scripts.agent_loop.settings") as st:
        st.THINKING_POLICY = "smart"
        st.THINK_FIRST_MODE = "off"
        st.THINK_FIRST = False
        st.EARLY_ABORT = False
        st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 120
        st.FEATURE_CODING_AUTO_TEST = False
        resp = _call_model(
            prov,
            hist,
            on_stream_delta=on_delta,
            on_thinking_start=on_thinking,
        )

    _check("got_thinking_event", "thinking" in events, str(events))
    write_idxs = [i for i, e in enumerate(events) if e.startswith("writing:")]
    think_idxs = [i for i, e in enumerate(events) if e == "thinking"]
    _check("has_writing", bool(write_idxs), str(events))
    _check(
        "thinking_before_writing",
        bool(think_idxs)
        and bool(write_idxs)
        and min(think_idxs) < min(write_idxs),
        str(events),
    )
    _check(
        "no_hidden_draft_in_ui",
        not any("HIDDEN_DRAFT" in e for e in events),
        str(events),
    )
    _check("final_ok", "VISIBLE_FINAL_ANSWER" in (resp.content or ""))
    _check("two_calls", prov.n == 2, str(prov.n))


def test_approver_sticky_flags_drive_phase() -> None:
    """Simulated approver state: thinking sticky → Thinking…, then Writing…."""
    from app.turn_phase import phase_from_turn

    # Mimic _push_live_activity after on_thinking_start
    p1 = phase_from_turn(
        waiting=False,
        checking=False,
        steps=[],
        warming=False,
        thinking=True,
        writing=False,
    )
    _check("sticky_thinking", p1["kind"] == "thinking", repr(p1))
    p2 = phase_from_turn(
        waiting=False,
        checking=False,
        steps=[],
        warming=False,
        thinking=False,
        writing=True,
    )
    _check("sticky_writing", p2["kind"] == "writing", repr(p2))
    # Later activity with no flags must not invent Working over sticky if we pass flags
    p3 = phase_from_turn(thinking=True, warming=False)
    _check("still_thinking_not_working", p3["kind"] == "thinking", repr(p3))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_phase_priority_thinking_beats_working()
    test_hide_draft_emits_thinking_before_writing()
    test_approver_sticky_flags_drive_phase()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
