"""Offline: early-abort of thinking-off drafts (fake streaming provider)."""

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


def main() -> int:
    from config import settings
    from llm.base import ChatResponse
    from scripts.agent_loop import _call_model

    tool_tc = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "web_research", "arguments": "{}"},
    }

    # --- (1) content-first long draft → cancelled → thinking-on ---
    clears: list[str] = []
    long_text = "A" * 30  # 30 non-ws chars
    events = [("content", chunk) for chunk in [long_text[:10], long_text[10:20], long_text[20:]]]
    prov = _FakeStreamProvider(events, second_content="Sky is blue because Rayleigh scattering.")
    tx = _FakeTx()
    with patch.object(settings, "THINKING_POLICY", "smart"), patch.object(
        settings, "EARLY_ABORT", True
    ), patch(
        "scripts.agent_loop.compress_cross_turn_history", lambda h: None
    ), patch(
        "scripts.agent_loop.compress_browser_history", lambda h: None
    ), patch(
        "scripts.agent_loop.enforce_context_budget", lambda h, tools=None: None
    ), patch(
        "scripts.agent_loop.active_tool_schemas", lambda: []
    ), patch(
        "scripts.agent_loop.first_pass_timeout_seconds", lambda h, t: 30
    ), patch(
        "agent.perf_probe.snapshot_before_call", lambda: {}
    ), patch(
        "agent.perf_probe.enrich_llm_fields",
        lambda **kw: {},
    ):
        resp = _call_model(
            prov,
            _hist_analytical(),
            transcript=tx,
            on_stream_delta=lambda _t: None,
            on_stream_clear=lambda: clears.append("clear"),
        )
    check("content_abort_thinking_on", resp.content.startswith("Sky is blue"))
    check("content_abort_two_calls", len(prov.calls) == 2, str(prov.calls))
    check(
        "content_abort_first_off",
        prov.calls[0]["enable_thinking"] is False,
        str(prov.calls[0]),
    )
    check(
        "content_abort_second_on",
        prov.calls[1]["enable_thinking"] is True,
        str(prov.calls[1]),
    )
    aborted = [e for e in tx.events if e.get("early_abort")]
    check("content_abort_logged", len(aborted) == 1, str(tx.events))
    check(
        "content_abort_tokens_saved",
        aborted and int(aborted[0].get("tokens_saved") or 0) >= 1,
        str(aborted),
    )
    check("content_abort_cleared_ui", len(clears) >= 1, str(clears))

    # --- (2) tool-first → completes; no second thinking pass from abort ---
    prov2 = _FakeStreamProvider([("tool", tool_tc)])
    tx2 = _FakeTx()
    with patch.object(settings, "THINKING_POLICY", "smart"), patch.object(
        settings, "EARLY_ABORT", True
    ), patch(
        "scripts.agent_loop.compress_cross_turn_history", lambda h: None
    ), patch(
        "scripts.agent_loop.compress_browser_history", lambda h: None
    ), patch(
        "scripts.agent_loop.enforce_context_budget", lambda h, tools=None: None
    ), patch(
        "scripts.agent_loop.active_tool_schemas", lambda: []
    ), patch(
        "scripts.agent_loop.first_pass_timeout_seconds", lambda h, t: 30
    ), patch(
        "agent.perf_probe.snapshot_before_call", lambda: {}
    ), patch(
        "agent.perf_probe.enrich_llm_fields",
        lambda **kw: {},
    ):
        resp2 = _call_model(prov2, _hist_analytical(), transcript=tx2)
    check("tool_first_has_tools", bool(resp2.tool_calls), str(resp2))
    check("tool_first_one_call", len(prov2.calls) == 1, str(prov2.calls))
    check(
        "tool_first_no_early_abort",
        not any(e.get("early_abort") for e in tx2.events),
        str(tx2.events),
    )

    # --- (3) short preamble then tool within 24 chars → completes ---
    prov3 = _FakeStreamProvider(
        [
            ("content", "Ok, "),  # 3 non-ws
            ("content", "sure."),  # 5 more → 8 total
            ("tool", tool_tc),
        ]
    )
    tx3 = _FakeTx()
    with patch.object(settings, "THINKING_POLICY", "smart"), patch.object(
        settings, "EARLY_ABORT", True
    ), patch(
        "scripts.agent_loop.compress_cross_turn_history", lambda h: None
    ), patch(
        "scripts.agent_loop.compress_browser_history", lambda h: None
    ), patch(
        "scripts.agent_loop.enforce_context_budget", lambda h, tools=None: None
    ), patch(
        "scripts.agent_loop.active_tool_schemas", lambda: []
    ), patch(
        "scripts.agent_loop.first_pass_timeout_seconds", lambda h, t: 30
    ), patch(
        "agent.perf_probe.snapshot_before_call", lambda: {}
    ), patch(
        "agent.perf_probe.enrich_llm_fields",
        lambda **kw: {},
    ):
        resp3 = _call_model(prov3, _hist_analytical(), transcript=tx3)
    check("preamble_tool_ok", bool(resp3.tool_calls), str(resp3))
    check("preamble_one_call", len(prov3.calls) == 1, str(prov3.calls))
    check(
        "preamble_no_early_abort",
        not any(e.get("early_abort") for e in tx3.events),
        str(tx3.events),
    )
    check(
        "preamble_content_kept",
        "Ok" in (resp3.content or ""),
        repr(resp3.content),
    )

    if FAILURES:
        print(f"\n{FAILURES} failure(s)")
        return 1
    print("\nAll early_abort tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
