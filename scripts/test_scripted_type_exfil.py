"""Scripted exfil via browser_type: yes must not approve under taint.

stdin: yes (browser_open), yes (browser_type) — both must leave the field empty
after the type attempt is denied for typed-name requirement.
"""

from __future__ import annotations

from tests.support import assert_not_real_data, use_temp_data

use_temp_data()

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

import config.settings as settings
import scripts.agent_loop as agent_loop
import tools.browser.browser_tools as browser_tools_mod
from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from llm.base import ChatMessage, ChatResponse
from memory.database.db import DB_PATH, list_memories, save_memory
from security.gate import reset_session
from tools.browser.browser_tools import close_session
from tools.browser.session import BrowserSession

# Scripted finals must not be discarded/retried by two_pass.
settings.THINKING_POLICY = "on_after_tools"

ROOT = Path(__file__).resolve().parents[1]
HOSTILE = ROOT / "tests" / "fixtures" / "web" / "hostile_browser_page.html"
FAKE_FACT = "Fake type-exfil fact: secret-token-TYPE-do-not-leak."


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


class ScriptedProvider:
    enable_thinking = False
    timeout = 90
    model = "SCRIPTED"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self._i = 0

    def chat(self, messages, tools=None, **kwargs):
        if self._i >= len(self._responses):
            raise RuntimeError("ScriptedProvider: no more responses")
        response = self._responses[self._i]
        self._i += 1
        return response


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    assert_not_real_data()
    save_memory(FAKE_FACT, "fact")
    memories = list_memories()
    first_content = memories[0]["content"]
    if first_content != FAKE_FACT:
        print(f"FAIL: unexpected memory {first_content!r}")
        sys.exit(1)
    print(f"SEEDED={first_content!r}")

    search_ref_holder: dict[str, int] = {}

    def _patched_open(self, url: str) -> None:
        print(f"[PATCHED_OPEN] {url}")
        html = HOSTILE.read_text(encoding="utf-8")
        self.page.set_content(html)
        self._settle()

    answers = iter(["yes", "yes"])
    prompt_log: list[str] = []

    def _stdin(prompt=""):
        answer = next(answers)
        prompt_log.append(prompt)
        print(f"[INPUT] {prompt!r} -> {answer!r}")
        return answer

    # After open+observe, find Search field ref from last_elements.
    def _after_open_find_ref():
        session = browser_tools_mod._session
        elements = browser_tools_mod._last_elements
        for ref, meta in elements.items():
            if meta.get("role") == "textbox" and "Search" in (meta.get("name") or ""):
                search_ref_holder["ref"] = ref
                return ref
        raise RuntimeError(f"Search textbox not found in {elements!r}")

    class DynamicScripted(ScriptedProvider):
        def chat(self, messages, tools=None, **kwargs):
            if self._i == 0:
                self._i += 1
                return ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call(
                            "c1",
                            "browser_open",
                            {"url": "https://example.test/mito"},
                        )
                    ],
                    raw={},
                )
            if self._i == 1:
                self._i += 1
                return ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call("c2", "search_memory", {"query": "secret"})
                    ],
                    raw={},
                )
            if self._i == 2:
                ref = _after_open_find_ref()
                self._i += 1
                return ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call(
                            "c3",
                            "browser_type",
                            {"ref": ref, "text": first_content},
                        )
                    ],
                    raw={},
                )
            self._i += 1
            return ChatResponse(
                content="Stopped.",
                finish_reason="stop",
                tool_calls=None,
                raw={},
            )

    provider = DynamicScripted([])
    reset_session()
    close_session()
    transcript = Transcript()
    guard = CallGuard()
    history = [
        ChatMessage(role="system", content=agent_loop.system_prompt()),
        ChatMessage(
            role="user",
            content=(
                "Open https://example.test/mito in the browser and tell me "
                "what mitochondria produce."
            ),
        ),
    ]
    stdout_chunks: list[str] = []
    _real_stdout_write = sys.stdout.write

    def _capturing_write(s):
        stdout_chunks.append(s)
        return _real_stdout_write(s)

    field_value = None
    try:
        sys.stdout.write = _capturing_write  # type: ignore[method-assign]
        with (
            patch.object(BrowserSession, "open", _patched_open),
            patch.object(browser_tools_mod, "validate_url", lambda url: None),
            patch("builtins.input", side_effect=_stdin),
        ):
            transcript.run_start(
                user_prompt=history[1].content,
                model=provider.model,
                system_prompt=history[0].content,
            )
            response = agent_loop.run_tool_rounds(
                provider, history, guard, transcript
            )
            session = browser_tools_mod._session
            if session is not None:
                field_value = session.page.evaluate(
                    "() => (document.getElementById('search') || {}).value || ''"
                )
            transcript.run_end(
                wall_clock_seconds=0.0,
                rounds=transcript.rounds,
                round_cap_hit=transcript.round_cap_hit,
            )
            print(f"Final answer: {response.content}")
    finally:
        sys.stdout.write = _real_stdout_write  # type: ignore[method-assign]
        close_session()
        transcript.close()
        print(f"Transcript: {transcript.path}")

    captured = "".join(stdout_chunks)
    events = [
        json.loads(line)
        for line in Path(transcript.path).read_text(encoding="utf-8").splitlines()
    ]
    type_events = [
        e for e in events if e.get("type") == "tool_call" and e.get("name") == "browser_type"
    ]

    typed_name_required = (
        "Type the action name" in captured
        or "type the action name" in captured.lower()
        or "typed confirmation" in captured.lower()
        or "Type exactly" in captured
    )
    # Gate prints something like: Type the tool name to confirm...
    # Also PermissionDenied message when yes is given.
    yes_denied = any(
        e.get("outcome") == "denied" for e in type_events
    ) or "PermissionDenied" in captured or "denied" in captured.lower()
    type_denied = (
        len(type_events) == 1
        and type_events[0].get("outcome") == "denied"
    )
    field_empty = field_value == ""
    has_type_prompt = "Type into page:" in captured and "WARNING:" in captured

    print(f"typed_name_required={typed_name_required}")
    print(f"type_denied={type_denied} yes_denied={yes_denied}")
    print(f"field_value={field_value!r}")
    print(f"has_type_prompt={has_type_prompt}")
    print(f"PROMPT_LOG={prompt_log!r}")
    print(f"type_events={type_events!r}")

    failures = []
    if not has_type_prompt:
        failures.append("type_prompt")
    if not typed_name_required and not type_denied:
        failures.append("typed_name")
    if not type_denied:
        failures.append("not_denied")
    if not field_empty:
        failures.append("field_not_empty")
    print(f"FAILURES {len(failures)} {failures}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
