"""Offline: early-abort of thinking-off drafts (fake streaming provider).

Round 9B: abort only when the turn already has a tool result (synthesis).
"""

from __future__ import annotations

import sys
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


class _FakeStreamProvider:
    """Scripted chat_stream: events are ('content', str) or ('tool', dict)."""

    def __init__(self, first_events: list, second_content: str = "Thoughtful answer.") -> None:
        self.first_events = list(first_events)
        self.second_content = second_content
        self.timeout = 30
        self.enable_thinking = False
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
        self.calls.append(
            {
                "enable_thinking": enable_thinking,
                "n_messages": len(messages or []),
            }
        )
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


class _FakeTx:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def llm_call(self, **fields: Any) -> None:
        self.events.append(dict(fields))


def _hist_analytical():
    from llm.base import ChatMessage

    return [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(role="user", content="Why is the sky blue? Explain."),
    ]


def _hist_synthesis():
    """History after a tool already ran this turn (synthesis call)."""
    from llm.base import ChatMessage

    return [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(role="user", content="Why is the sky blue? Explain."),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_research", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(
            role="tool",
            content='{"summary": "Rayleigh scattering"}',
            tool_call_id="call_1",
            name="web_research",
        ),
    ]


def _patches():
    from config import settings

    return [
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


def main() -> int:
    from scripts.agent_loop import _call_model

    tool_tc = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "web_research", "arguments": "{}"},
    }

    # --- (1) synthesis + long content draft → early abort → thinking-on ---
    clears: list[str] = []
    long_text = "A" * 30  # 30 non-ws chars
    events = [
        ("content", chunk)
        for chunk in [long_text[:10], long_text[10:20], long_text[20:]]
    ]
    prov = _FakeStreamProvider(
        events, second_content="Sky is blue because Rayleigh scattering."
    )
    tx = _FakeTx()
    ctx = _patches()
    for p in ctx:
        p.start()
    try:
        resp = _call_model(
            prov,
            _hist_synthesis(),
            transcript=tx,
            on_stream_delta=lambda _t: None,
            on_stream_clear=lambda: clears.append("clear"),
        )
    finally:
        for p in reversed(ctx):
            p.stop()
    check("synth_abort_thinking_on", resp.content.startswith("Sky is blue"))
    check("synth_abort_two_calls", len(prov.calls) == 2, str(prov.calls))
    check(
        "synth_abort_first_off",
        prov.calls[0]["enable_thinking"] is False,
        str(prov.calls[0]),
    )
    check(
        "synth_abort_second_on",
        prov.calls[1]["enable_thinking"] is True,
        str(prov.calls[1]),
    )
    aborted = [e for e in tx.events if e.get("early_abort")]
    check("synth_abort_logged", len(aborted) == 1, str(tx.events))
    check(
        "synth_abort_tokens_saved",
        aborted and int(aborted[0].get("tokens_saved") or 0) >= 1,
        str(aborted),
    )
    check("synth_abort_cleared_ui", len(clears) >= 1, str(clears))

    # --- (1b) first call of turn + long content → NO early abort ---
    # (still discarded for thinking-on final answer when no tools)
    prov1b = _FakeStreamProvider(
        events, second_content="Sky is blue because Rayleigh scattering."
    )
    tx1b = _FakeTx()
    ctx = _patches()
    for p in ctx:
        p.start()
    try:
        resp1b = _call_model(
            prov1b,
            _hist_analytical(),
            transcript=tx1b,
            on_stream_delta=lambda _t: None,
            on_stream_clear=lambda: None,
        )
    finally:
        for p in reversed(ctx):
            p.stop()
    check(
        "first_call_no_early_abort",
        not any(e.get("early_abort") for e in tx1b.events),
        str(tx1b.events),
    )
    check(
        "first_call_still_thinking_on",
        resp1b.content.startswith("Sky is blue"),
        repr(resp1b.content),
    )

    # --- (2) tool-first on first call → completes; no early abort ---
    prov2 = _FakeStreamProvider([("tool", tool_tc)])
    tx2 = _FakeTx()
    ctx = _patches()
    for p in ctx:
        p.start()
    try:
        resp2 = _call_model(prov2, _hist_analytical(), transcript=tx2)
    finally:
        for p in reversed(ctx):
            p.stop()
    check("tool_first_has_tools", bool(resp2.tool_calls), str(resp2))
    check("tool_first_one_call", len(prov2.calls) == 1, str(prov2.calls))
    check(
        "tool_first_no_early_abort",
        not any(e.get("early_abort") for e in tx2.events),
        str(tx2.events),
    )

    # --- (3) analytical first call: long preamble then tool → must complete ---
    long_preamble = "I'll check the files in that folder now. "
    assert sum(1 for c in long_preamble if not c.isspace()) >= 24
    # Stream preamble in chunks that would trip the old early-abort threshold
    # before the tool delta arrives.
    mid = len(long_preamble) // 2
    prov3 = _FakeStreamProvider(
        [
            ("content", long_preamble[:mid]),
            ("content", long_preamble[mid:]),
            ("tool", tool_tc),
        ]
    )
    tx3 = _FakeTx()
    ctx = _patches()
    for p in ctx:
        p.start()
    try:
        resp3 = _call_model(prov3, _hist_analytical(), transcript=tx3)
    finally:
        for p in reversed(ctx):
            p.stop()
    check("preamble_tool_ok", bool(resp3.tool_calls), str(resp3))
    check("preamble_one_call", len(prov3.calls) == 1, str(prov3.calls))
    check(
        "preamble_no_early_abort",
        not any(e.get("early_abort") for e in tx3.events),
        str(tx3.events),
    )
    check(
        "preamble_content_kept",
        "check the files" in (resp3.content or ""),
        repr(resp3.content),
    )

    # --- (4) short preamble then tool (legacy) ---
    prov4 = _FakeStreamProvider(
        [
            ("content", "Ok, "),
            ("content", "sure."),
            ("tool", tool_tc),
        ]
    )
    tx4 = _FakeTx()
    ctx = _patches()
    for p in ctx:
        p.start()
    try:
        resp4 = _call_model(prov4, _hist_analytical(), transcript=tx4)
    finally:
        for p in reversed(ctx):
            p.stop()
    check("short_preamble_tool_ok", bool(resp4.tool_calls), str(resp4))
    check(
        "short_preamble_no_early_abort",
        not any(e.get("early_abort") for e in tx4.events),
        str(tx4.events),
    )

    if FAILURES:
        print(f"\n{FAILURES} failure(s)")
        return 1
    print("\nAll early_abort tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
