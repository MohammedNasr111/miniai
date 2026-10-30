"""Round 9F Part 1 — thinking-off draft never streams to the UI when want_second."""

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


class _TwoPassProvider:
    """First call (thinking off) returns a final; second (thinking on) streams."""

    def __init__(self) -> None:
        self.n = 0
        self.timeout = 60
        self.enable_thinking = False
        self.streamed_thinking_flags: list[bool] = []

    def chat(self, messages, tools=None, **kwargs):
        return self.chat_stream(messages, tools=tools, **kwargs)

    def chat_stream(self, messages, tools=None, **kwargs):
        thinking = bool(kwargs.get("enable_thinking", False))
        on_token = kwargs.get("on_token")
        self.n += 1
        self.streamed_thinking_flags.append(thinking)
        if not thinking:
            # Draft that would have been shown then erased in 9E-off-without-hide.
            draft = "DRAFT_SHOULD_NOT_REACH_UI " * 5
            if on_token is not None:
                on_token(draft)
            return ChatResponse(
                content=draft,
                finish_reason="stop",
                tool_calls=None,
                raw={},
            )
        final = "FINAL_VISIBLE_ANSWER about CPU caches."
        if on_token is not None:
            on_token(final)
        return ChatResponse(
            content=final,
            finish_reason="stop",
            tool_calls=None,
            raw={},
        )


def test_hide_draft_zero_ui_deltas_then_stream_final() -> None:
    from scripts.agent_loop import _call_model

    prov = _TwoPassProvider()
    ui_deltas: list[str] = []
    thinking_starts: list[int] = []

    def on_delta(text: str) -> None:
        ui_deltas.append(text)

    hist = [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(
            role="user",
            content="In about 150 words, explain how a CPU cache works.",
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
            on_thinking_start=lambda: thinking_starts.append(1),
        )
    # Draft must not appear in UI deltas; only thinking-on content.
    draft_leaks = [d for d in ui_deltas if "DRAFT_SHOULD_NOT_REACH_UI" in d]
    _check("zero_draft_ui_deltas", not draft_leaks, str(ui_deltas))
    _check(
        "final_streamed",
        any("FINAL_VISIBLE_ANSWER" in d for d in ui_deltas),
        str(ui_deltas),
    )
    _check("thinking_ui_shown", len(thinking_starts) >= 1)
    _check("two_model_calls", prov.n == 2, str(prov.n))
    _check("off_then_on", prov.streamed_thinking_flags == [False, True])
    _check("response_is_final", "FINAL_VISIBLE_ANSWER" in (resp.content or ""))


def test_default_mode_is_off() -> None:
    import importlib

    import config.settings as st

    # Re-read would need env; assert module default after import with no override.
    # Process may have env set — check the constant documentation path.
    raw = getattr(st, "THINK_FIRST_MODE", None)
    _check("think_first_mode_attr", raw in ("off", "on", "gated"), str(raw))
    # Fresh parse of default string in source
    src = Path(st.__file__).read_text(encoding="utf-8")
    _check(
        "default_off_in_source",
        'get("MINIAI_THINK_FIRST", "off")' in src,
    )


def main() -> int:
    test_hide_draft_zero_ui_deltas_then_stream_final()
    test_default_mode_is_off()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
