"""Offline check that two_pass discards a final answer and retries with thinking on."""

from __future__ import annotations

import sys
from unittest.mock import patch

import config.settings as settings
from agent.transcript import Transcript
from llm.base import ChatMessage, ChatResponse
from scripts.agent_loop import _call_model

FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


class FakeProvider:
    enable_thinking = False
    timeout = 90

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append(dict(kwargs))
        n = len(self.calls)
        if n == 1:
            return ChatResponse(
                content="premature answer",
                finish_reason="stop",
                tool_calls=None,
                raw={"usage": {"prompt_tokens": 1, "completion_tokens": 2}},
            )
        return ChatResponse(
            content="final with thinking",
            finish_reason="stop",
            tool_calls=None,
            raw={"usage": {"prompt_tokens": 1, "completion_tokens": 3}},
        )


def test_two_pass_discards() -> None:
    provider = FakeProvider()
    history = [ChatMessage(role="user", content="hi")]
    transcript = Transcript()
    old = settings.THINKING_POLICY
    try:
        settings.THINKING_POLICY = "two_pass"
        response = _call_model(provider, history, transcript)
        transcript.close()
        lines = transcript.path.read_text(encoding="utf-8").splitlines()
        import json

        events = [json.loads(line) for line in lines]
        llm = [e for e in events if e.get("type") == "llm_call"]
        ok = (
            len(provider.calls) == 2
            and provider.calls[0].get("enable_thinking") is False
            and provider.calls[1].get("enable_thinking") is True
            and len(llm) == 2
            and llm[0].get("discarded") is True
            and llm[0].get("enable_thinking") is False
            and "discarded" not in llm[1]
            and response.content == "final with thinking"
        )
        report("two_pass_discard", ok, f"calls={provider.calls} llm={llm}")
    finally:
        settings.THINKING_POLICY = old
        transcript.close()


def test_default_unchanged() -> None:
    provider = FakeProvider()
    # Only one call expected under on_after_tools with empty history (no tools).
    provider.calls.clear()

    class OnceProvider(FakeProvider):
        def chat(self, messages, tools=None, **kwargs):
            self.calls.append(dict(kwargs))
            return ChatResponse(
                content="ok",
                finish_reason="stop",
                tool_calls=None,
                raw={"usage": {}},
            )

    p = OnceProvider()
    old = settings.THINKING_POLICY
    try:
        settings.THINKING_POLICY = "on_after_tools"
        response = _call_model(p, [ChatMessage(role="user", content="hi")], None)
        ok = len(p.calls) == 1 and response.content == "ok"
        report("default_one_call", ok, f"calls={p.calls}")
    finally:
        settings.THINKING_POLICY = old


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_two_pass_discards()
    test_default_unchanged()
    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
