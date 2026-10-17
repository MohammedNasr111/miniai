"""Offline checks for interactive chat (scripted provider, no LLM)."""

from __future__ import annotations

from tests.support import assert_not_real_data, use_temp_data

use_temp_data()

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

import config.settings as settings
from agent.executor.guard import CallGuard
from llm.base import ChatMessage, ChatResponse
from security.gate import is_tainted, reset_session, untrusted_sources
from tools.browser import browser_tools
from tools.browser.browser_tools import close_session
from tools.browser.session import BrowserSession
from tools.registry import TOOL_FUNCTIONS

from scripts.agent_loop import CROSS_TURN_OMITTED, compress_cross_turn_history
from scripts.chat import (
    end_session,
    handle_command,
    new_session,
    run_user_turn,
    status_text,
)
from tests.support import answer_by_action

settings.THINKING_POLICY = "on_after_tools"

FAILURES: list[str] = []
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "web" / "hostile_browser_page.html"


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _tool_call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
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
        # Attach fake usage for /status / warn tests.
        response.raw = {
            "usage": {"prompt_tokens": 100 + self._i * 10, "completion_tokens": 5}
        }
        return response


def _matched(history: list[ChatMessage]) -> bool:
    pending: set[str] = set()
    for message in history:
        if message.role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                cid = call.get("id")
                if cid:
                    pending.add(cid)
        elif message.role == "tool" and message.tool_call_id:
            pending.discard(message.tool_call_id)
    return not pending


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    assert_not_real_data()
    tmp = tempfile.mkdtemp(prefix="miniai_chat_")

    def _launch():
        return BrowserSession(headless=True, profile_dir=tmp)

    # --- 1: browser stays open; click uses turn-1 ref ---
    reset_session()
    close_session()
    click_ref_holder: dict[str, int] = {"ref": 1}
    responses1 = [
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=[
                _tool_call("o1", "browser_open", {"url": "https://example.com"})
            ],
        ),
        ChatResponse(content="opened", finish_reason="stop", tool_calls=None),
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=[_tool_call("c1", "browser_click", {"ref": 0})],  # filled later
        ),
        ChatResponse(content="clicked", finish_reason="stop", tool_calls=None),
    ]

    def _fill_click_ref():
        # After turn 1, patch the pending click args.
        ref = click_ref_holder["ref"]
        responses1[2].tool_calls = [
            _tool_call("c1", "browser_click", {"ref": ref})
        ]

    with patch.object(browser_tools, "_launch_session", side_effect=_launch):
        # Use set_content fixture instead of real navigate for stability.
        real_open = BrowserSession.open

        def _open_fixture(self, url: str) -> None:
            html = FIXTURE.read_text(encoding="utf-8")
            self.page.set_content(html)
            self._settle()
            from security.provenance import remember_url

            remember_url(url)
            self._last_open_mono = __import__("time").monotonic()

        with patch.object(BrowserSession, "open", _open_fixture):
            provider = ScriptedProvider(responses1)
            session = new_session(provider)
            with answer_by_action(
                {"browser_open": "yes", "browser_click": "yes"}
            ):
                a1 = run_user_turn(session, "open the page")
                # Pick a clickable button/link ref from observation.
                elems = browser_tools._last_elements
                clickable = [
                    r
                    for r, m in elems.items()
                    if m.get("role") in ("button", "link")
                ]
                click_ref_holder["ref"] = clickable[0] if clickable else 1
                _fill_click_ref()
                a2 = run_user_turn(session, "click the first button")
            ok1 = (
                a1 == "opened"
                and a2 == "clicked"
                and browser_tools._session is not None
                and browser_tools._session.is_alive()
            )
            report("1", ok1, f"a1={a1!r} a2={a2!r} refs={list(elems)[:5]}")
            end_session(session)

    # --- 2: taint persists; write_file yes denied ---
    reset_session()
    close_session()
    with patch.object(browser_tools, "_launch_session", side_effect=_launch):
        with patch.object(BrowserSession, "open", _open_fixture):
            provider = ScriptedProvider(
                [
                    ChatResponse(
                        content="",
                        finish_reason="tool_calls",
                        tool_calls=[
                            _tool_call(
                                "t1", "browser_open", {"url": "https://example.com"}
                            )
                        ],
                    ),
                    ChatResponse(
                        content="read web", finish_reason="stop", tool_calls=None
                    ),
                    ChatResponse(
                        content="",
                        finish_reason="tool_calls",
                        tool_calls=[
                            _tool_call(
                                "w1",
                                "write_file",
                                {"path": str(ROOT / "_chat_taint_test.txt"), "content": "x"},
                            )
                        ],
                    ),
                    ChatResponse(
                        content="wrote?", finish_reason="stop", tool_calls=None
                    ),
                ]
            )
            session = new_session(provider)
            captured: list[str] = []

            def _recording_input(prompt=""):
                captured.append(prompt)
                if "write_file" in prompt or "Type write_file" in prompt:
                    return "yes"
                return "yes"

            with patch("builtins.input", side_effect=_recording_input):
                # First turn: gate gets yes for browser_open
                run_user_turn(session, "open")
                assert is_tainted()
                run_user_turn(session, "write something")
            denied = any(
                "Denied" in (m.content or "")
                for m in session.history
                if m.role == "tool"
            )
            typed_prompt = any("Type write_file" in p for p in captured) or any(
                "write_file" in p and "Type" in p for p in captured
            )
            # Check gate printed typed confirmation somehow
            ok2 = is_tainted() and (
                typed_prompt
                or any("Typed confirmation" in (m.content or "") for m in session.history if m.role == "tool")
            )
            report(
                "2",
                ok2,
                f"tainted={is_tainted()} sources={untrusted_sources()} "
                f"captured={captured!r} denied_tool={denied}",
            )
            end_session(session)

    # --- 3: chat "Yes, go ahead." is not an approval ---
    reset_session()
    close_session()
    mark_path = ROOT / "_chat_delete_test.txt"
    mark_path.write_text("temp", encoding="utf-8")
    try:
        from security.gate import mark_untrusted

        provider = ScriptedProvider(
            [
                ChatResponse(
                    content="acknowledged", finish_reason="stop", tool_calls=None
                ),
                ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call("d1", "delete_file", {"path": str(mark_path)})
                    ],
                ),
                ChatResponse(content="deleted?", finish_reason="stop", tool_calls=None),
            ]
        )
        session = new_session(provider)
        mark_untrusted("browser_open")  # after new_session (which resets)
        prompts3: list[str] = []

        def _in3(prompt=""):
            prompts3.append(prompt)
            return "yes"  # should NOT be enough when tainted

        with patch("builtins.input", side_effect=_in3):
            run_user_turn(session, "Yes, go ahead.")
            run_user_turn(session, "now delete it")
        still_there = mark_path.exists()
        denied3 = any(
            "Denied" in (m.content or "") or "Typed confirmation" in (m.content or "")
            for m in session.history
            if m.role == "tool"
        )
        ok3 = still_there and denied3 and is_tainted()
        report(
            "3",
            ok3,
            f"exists={still_there} denied={denied3} prompts={prompts3!r}",
        )
        end_session(session)
    finally:
        if mark_path.exists():
            mark_path.unlink()

    # --- 4: /new clears taint, browser, guard, history ---
    reset_session()
    close_session()
    with patch.object(browser_tools, "_launch_session", side_effect=_launch):
        with patch.object(BrowserSession, "open", _open_fixture):
            provider = ScriptedProvider(
                [
                    ChatResponse(
                        content="",
                        finish_reason="tool_calls",
                        tool_calls=[
                            _tool_call(
                                "n1", "browser_open", {"url": "https://example.com"}
                            )
                        ],
                    ),
                    ChatResponse(content="ok", finish_reason="stop", tool_calls=None),
                ]
            )
            session = new_session(provider)
            with answer_by_action({"browser_open": "yes"}):
                run_user_turn(session, "open")
            assert is_tainted()
            assert browser_tools._session is not None
            old_guard = session.guard
            session, _ = handle_command(session, "/new", provider)
            ok4 = (
                not is_tainted()
                and untrusted_sources() == []
                and browser_tools._session is None
                and len(session.history) == 1
                and session.history[0].role == "system"
                and session.guard is not old_guard
                and session.turn_count == 0
            )
            # write_file prompt back to yes/no: check via gate with yes
            from security.gate import Tier, check_permission

            prompts4: list[str] = []

            def _in4(prompt=""):
                prompts4.append(prompt)
                return "yes"

            with patch("builtins.input", side_effect=_in4):
                check_permission("write_file", Tier.CONFIRM, "Write test")
            ok4 = ok4 and any("Allow? [yes/no]" in p for p in prompts4)
            report("4", ok4, f"tainted={is_tainted()} hist={len(session.history)} prompts={prompts4!r}")
            end_session(session)

    # --- 5: Ctrl+C mid-turn restores pre-turn history ---
    reset_session()
    close_session()
    provider = ScriptedProvider(
        [
            ChatResponse(content="hi", finish_reason="stop", tool_calls=None),
        ]
    )
    session = new_session(provider)
    run_user_turn(session, "hello")
    pre = len(session.history)

    class BoomProvider(ScriptedProvider):
        def chat(self, messages, tools=None, **kwargs):
            raise KeyboardInterrupt()

    session.provider = BoomProvider([])
    raised = False
    try:
        run_user_turn(session, "this will cancel")
    except KeyboardInterrupt:
        raised = True
    ok5 = (
        raised
        and len(session.history) == pre
        and _matched(session.history)
    )
    report("5", ok5, f"len={len(session.history)} pre={pre} matched={_matched(session.history)}")
    end_session(session)

    # --- 6: cross-turn compression ---
    reset_session()
    close_session()
    with patch.object(browser_tools, "_launch_session", side_effect=_launch):
        with patch.object(BrowserSession, "open", _open_fixture):
            # Different looking_for so observe is not blocked as a duplicate.
            responses6 = [
                ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call("b0", "browser_open", {"url": "https://example.com"})
                    ],
                ),
                ChatResponse(content="turn0", finish_reason="stop", tool_calls=None),
                ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call("b1", "browser_observe", {"looking_for": "one"})
                    ],
                ),
                ChatResponse(content="turn1", finish_reason="stop", tool_calls=None),
                ChatResponse(
                    content="",
                    finish_reason="tool_calls",
                    tool_calls=[
                        _tool_call("b2", "browser_observe", {"looking_for": "two"})
                    ],
                ),
                ChatResponse(content="turn2", finish_reason="stop", tool_calls=None),
            ]
            provider = ScriptedProvider(responses6)
            session = new_session(provider)
            with answer_by_action({"browser_open": "yes"}):
                run_user_turn(session, "t0")
                run_user_turn(session, "t1")
                run_user_turn(session, "t2")
            # Snapshot history and apply compression as _call_model would
            # before a 4th turn's model call: append a synthetic user msg.
            hist = [m.model_copy(deep=True) for m in session.history]
            hist.append(ChatMessage(role="user", content="t3"))
            before_ids = [m.tool_call_id for m in hist if m.role == "tool"]
            before_n = len(hist)
            compress_cross_turn_history(hist)
            tools = [m for m in hist if m.role == "tool"]
            # Latest browser obs (b2) intact; earlier-turn tools omitted.
            latest = tools[-1].content if tools else ""
            earlier = [m.content for m in tools[:-1]]
            ok6 = (
                len(hist) == before_n
                and [m.tool_call_id for m in tools] == before_ids
                and all(c == CROSS_TURN_OMITTED for c in earlier)
                and latest != CROSS_TURN_OMITTED
                and "Untrusted" in latest
            )
            report(
                "6",
                ok6,
                f"n_tools={len(tools)} earlier={earlier!r} "
                f"latest_start={latest[:40]!r}",
            )
            end_session(session)

    # --- 7: /status ---
    reset_session()
    close_session()
    with patch.object(browser_tools, "_launch_session", side_effect=_launch):
        with patch.object(BrowserSession, "open", _open_fixture):
            provider = ScriptedProvider(
                [
                    ChatResponse(
                        content="",
                        finish_reason="tool_calls",
                        tool_calls=[
                            _tool_call(
                                "s1", "browser_open", {"url": "https://example.com"}
                            )
                        ],
                    ),
                    ChatResponse(content="ok", finish_reason="stop", tool_calls=None),
                ]
            )
            session = new_session(provider)
            with answer_by_action({"browser_open": "yes"}):
                run_user_turn(session, "open")
            text = status_text(session)
            ok7 = (
                "browser_open" in text
                and "Turns: 1" in text
                and "Last prompt_tokens:" in text
            )
            report("7", ok7, f"status={text!r}")
            end_session(session)

    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
