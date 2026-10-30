"""Round 10 Part 0 — hide-draft ON: thinking-off draft never streams to the UI.

Architect decision (ROUND_10): hide-draft is UI-only; battery cannot measure it.
Assert zero erased draft deltas, then the thinking pass streams.
"""

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

    hist = [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(
            role="user",
            content="In about 150 words, explain how a CPU cache works.",
        ),
    ]
    with patch("scripts.agent_loop.settings") as st:
        # Force off so we exercise the two-pass + hide-draft path (not think-first).
        st.THINKING_POLICY = "smart"
        st.THINK_FIRST_MODE = "off"
        st.THINK_FIRST = False
        st.EARLY_ABORT = False
        st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 120
        st.FEATURE_CODING_AUTO_TEST = False
        resp = _call_model(
            prov,
            hist,
            on_stream_delta=lambda text: ui_deltas.append(text),
            on_thinking_start=lambda: thinking_starts.append(1),
        )
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


def test_default_mode_is_gated() -> None:
    import config.settings as st

    raw = getattr(st, "THINK_FIRST_MODE", None)
    _check("think_first_mode_attr", raw in ("off", "on", "gated"), str(raw))
    src = Path(st.__file__).read_text(encoding="utf-8")
    _check(
        "default_gated_in_source",
        'get("MINIAI_THINK_FIRST", "gated")' in src,
    )


def main() -> int:
    test_hide_draft_zero_ui_deltas_then_stream_final()
    test_default_mode_is_gated()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
