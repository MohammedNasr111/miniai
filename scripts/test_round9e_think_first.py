"""Round 9E Part 2 — think-first skips discarded thinking-off analytical drafts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from llm.base import ChatMessage, ChatResponse

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" — {detail}" if detail else ""))


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.timeout = 60
        self.enable_thinking = False

    def chat(self, messages, tools=None, **kwargs):
        thinking = bool(kwargs.get("enable_thinking", False))
        self.calls.append(thinking)
        return ChatResponse(
            content="A CPU cache holds recently used data near the core.",
            finish_reason="stop",
            tool_calls=None,
            raw={},
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        return self.chat(messages, tools=tools, **kwargs)


def _analytical_history() -> list:
    return [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(
            role="user",
            content="In about 150 words, explain how a CPU cache works.",
        ),
    ]


def test_think_first_on_skips_draft() -> None:
    from scripts.agent_loop import _call_model

    prov = _RecordingProvider()
    thinking_starts = []
    with patch("scripts.agent_loop.settings") as st:
        st.THINKING_POLICY = "smart"
        st.THINK_FIRST = True
        st.EARLY_ABORT = False
        st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 120
        st.FEATURE_CODING_AUTO_TEST = False
        resp = _call_model(
            prov,
            _analytical_history(),
            on_thinking_start=lambda: thinking_starts.append(1),
        )
    _check("think_first_one_call", len(prov.calls) == 1, str(prov.calls))
    _check("think_first_thinking_on", prov.calls == [True], str(prov.calls))
    _check("think_first_ui_hook", len(thinking_starts) == 1)
    _check("think_first_has_answer", "cache" in (resp.content or "").lower())


def test_think_first_off_two_pass_discard() -> None:
    from scripts.agent_loop import _call_model

    prov = _RecordingProvider()
    with patch("scripts.agent_loop.settings") as st:
        st.THINKING_POLICY = "smart"
        st.THINK_FIRST = False
        st.EARLY_ABORT = False
        st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 120
        st.FEATURE_CODING_AUTO_TEST = False
        _call_model(prov, _analytical_history())
    _check("think_first_off_two_calls", len(prov.calls) == 2, str(prov.calls))
    _check(
        "think_first_off_off_then_on",
        prov.calls == [False, True],
        str(prov.calls),
    )


def test_synthesis_keeps_thinking_off_first() -> None:
    """Tool result in current turn → still thinking-off first (no think-first)."""
    from scripts.agent_loop import _call_model

    hist = _analytical_history() + [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(role="tool", content="some evidence", tool_call_id="1"),
    ]
    # Analytical with evidence tools → want_second True, but turn_has_tool_result.
    prov = _RecordingProvider()

    def chat_with_tools(messages, tools=None, **kwargs):
        thinking = bool(kwargs.get("enable_thinking", False))
        prov.calls.append(thinking)
        # First call returns a final (no tools) so second pass can run.
        return ChatResponse(
            content="Based on the evidence, caches are fast.",
            finish_reason="stop",
            tool_calls=None,
            raw={},
        )

    prov.chat = chat_with_tools  # type: ignore[method-assign]
    prov.chat_stream = chat_with_tools  # type: ignore[method-assign]
    with patch("scripts.agent_loop.settings") as st:
        st.THINKING_POLICY = "smart"
        st.THINK_FIRST = True
        st.EARLY_ABORT = False
        st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 120
        st.FEATURE_CODING_AUTO_TEST = False
        with patch(
            "scripts.agent_loop.should_run_thinking_second_pass", return_value=True
        ):
            _call_model(prov, hist)
    _check("synthesis_two_calls", len(prov.calls) == 2, str(prov.calls))
    _check(
        "synthesis_off_then_on",
        prov.calls == [False, True],
        str(prov.calls),
    )


def main() -> int:
    test_think_first_on_skips_draft()
    test_think_first_off_two_pass_discard()
    test_synthesis_keeps_thinking_off_first()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
