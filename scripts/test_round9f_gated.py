"""Round 9F Part 2 — gated think-first only when the question has no tool cues."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from llm.base import ChatMessage, ChatResponse
from scripts.agent_loop import question_has_tool_cues

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" — {detail}" if detail else ""))


class _RecProv:
    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.timeout = 60
        self.enable_thinking = False

    def chat(self, messages, tools=None, **kwargs):
        thinking = bool(kwargs.get("enable_thinking", False))
        self.calls.append(thinking)
        return ChatResponse(
            content="ok",
            finish_reason="stop",
            tool_calls=None,
            raw={},
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        return self.chat(messages, tools=tools, **kwargs)


def test_cue_detection() -> None:
    _check(
        "cpu_cache_no_cues",
        not question_has_tool_cues(
            "In about 150 words, explain how a CPU cache works."
        ),
    )
    _check(
        "project_path_has_cues",
        question_has_tool_cues(
            r"Find and fix the bugs in my project at C:\Users\me\proj"
        ),
    )
    _check(
        "warranty_pdf_has_cues",
        question_has_tool_cues(
            "What does the warranty.pdf say and which page?"
        ),
    )
    _check(
        "downloads_word",
        question_has_tool_cues("What are the 3 biggest files in Downloads?"),
    )


def _run(mode: str, question: str) -> list[bool]:
    from scripts.agent_loop import _call_model

    prov = _RecProv()
    hist = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content=question),
    ]
    with patch("scripts.agent_loop.settings") as st:
        st.THINKING_POLICY = "smart"
        st.THINK_FIRST_MODE = mode
        st.THINK_FIRST = mode == "on"
        st.EARLY_ABORT = False
        st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 120
        st.FEATURE_CODING_AUTO_TEST = False
        _call_model(prov, hist)
    return prov.calls


def test_gated_cpu_think_first() -> None:
    calls = _run(
        "gated",
        "In about 150 words, explain how a CPU cache works.",
    )
    _check("gated_cpu_one_thinking_on", calls == [True], str(calls))


def test_gated_project_not_think_first() -> None:
    # No want_second (not analytical) → single thinking-off call (not think-first).
    calls = _run(
        "gated",
        r"Find and fix the bugs in my project at C:\Users\me\code",
    )
    _check("gated_project_thinking_off", calls == [False], str(calls))


def test_gated_pdf_not_think_first() -> None:
    calls = _run(
        "gated",
        "What does the warranty.pdf say in the temp folder and which page?",
    )
    _check("gated_pdf_thinking_off", calls == [False], str(calls))


def test_gated_analytical_with_cues_uses_9d() -> None:
    # Analytical + tool cues → want_second but not think-first → off then on.
    calls = _run(
        "gated",
        r"How do I fix the bugs in my project at C:\Users\me\code?",
    )
    _check("gated_analytical_cues_off_then_on", calls == [False, True], str(calls))


def main() -> int:
    test_cue_detection()
    test_gated_cpu_think_first()
    test_gated_project_not_think_first()
    test_gated_pdf_not_think_first()
    test_gated_analytical_with_cues_uses_9d()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
