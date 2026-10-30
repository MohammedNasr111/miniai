"""Round 9F Part 1 — hide-draft keep failed; assert feature is switched off.

Keep rule: off battery mean ≥ 15. Measured mean 14.0
(logs/round9f_battery_off.json). Standing rule: fail → switch off.
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
            draft = "DRAFT_MAY_REACH_UI " * 5
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


def test_hide_draft_switched_off_streams_draft() -> None:
    from scripts.agent_loop import _call_model

    prov = _TwoPassProvider()
    ui_deltas: list[str] = []

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
            on_stream_delta=lambda text: ui_deltas.append(text),
        )
    # Keep failed → hide_draft off → thinking-off draft may reach UI before clear.
    _check(
        "draft_may_reach_ui",
        any("DRAFT_MAY_REACH_UI" in d for d in ui_deltas),
        str(ui_deltas),
    )
    _check(
        "final_streamed",
        any("FINAL_VISIBLE_ANSWER" in d for d in ui_deltas),
        str(ui_deltas),
    )
    _check("two_model_calls", prov.n == 2, str(prov.n))
    _check("off_then_on", prov.streamed_thinking_flags == [False, True])
    _check("response_is_final", "FINAL_VISIBLE_ANSWER" in (resp.content or ""))


def test_default_mode_is_off() -> None:
    import config.settings as st

    raw = getattr(st, "THINK_FIRST_MODE", None)
    _check("think_first_mode_attr", raw in ("off", "on", "gated"), str(raw))
    src = Path(st.__file__).read_text(encoding="utf-8")
    _check(
        "default_off_in_source",
        'get("MINIAI_THINK_FIRST", "off")' in src,
    )


def main() -> int:
    test_hide_draft_switched_off_streams_draft()
    test_default_mode_is_off()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
