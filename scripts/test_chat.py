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

import requests

from scripts.agent_loop import (
    CROSS_TURN_OMITTED,
    QUOTE_CHECK_NOTE,
    check_quotes_against_evidence,
    compress_cross_turn_history,
    first_pass_timeout_seconds,
    get_evidence,
    history_char_count,
    prompt_size_estimate,
    reset_evidence,
)
from scripts.chat import (
    TURN_TIMEOUT_MESSAGE,
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

    # --- 5b: ReadTimeout mid-turn rolls back; next turn works ---
    reset_session()
    close_session()
    with patch.object(browser_tools, "_launch_session", side_effect=_launch):
        with patch.object(BrowserSession, "open", _open_fixture):
            provider5b = ScriptedProvider(
                [
                    ChatResponse(
                        content="",
                        finish_reason="tool_calls",
                        tool_calls=[
                            _tool_call(
                                "to1",
                                "browser_open",
                                {"url": "https://example.com"},
                            )
                        ],
                    ),
                    ChatResponse(
                        content="opened ok", finish_reason="stop", tool_calls=None
                    ),
                    # After timeout recovery, next turn:
                    ChatResponse(
                        content="recovered", finish_reason="stop", tool_calls=None
                    ),
                ]
            )
            session5b = new_session(provider5b)
            with answer_by_action({"browser_open": "yes"}):
                a_ok = run_user_turn(session5b, "open please")
            pre5b = len(session5b.history)
            matched_before = _matched(session5b.history)

            class TimeoutProvider(ScriptedProvider):
                def chat(self, messages, tools=None, **kwargs):
                    raise requests.ReadTimeout("simulated timeout")

            session5b.provider = TimeoutProvider([])
            msg_to = run_user_turn(session5b, "this will time out")
            rolled = (
                len(session5b.history) == pre5b
                and _matched(session5b.history)
                and matched_before
                and msg_to == TURN_TIMEOUT_MESSAGE
            )
            # Transcript should have turn_error
            turn_err = False
            if session5b.transcript is not None:
                for line in session5b.transcript.path.read_text(
                    encoding="utf-8"
                ).splitlines():
                    rec = json.loads(line)
                    if rec.get("type") == "turn_error":
                        turn_err = rec.get("error") == "ReadTimeout"
                        break
            session5b.provider = provider5b
            a_next = run_user_turn(session5b, "hello again")
            ok5b = (
                rolled
                and turn_err
                and a_ok == "opened ok"
                and a_next == "recovered"
                and _matched(session5b.history)
            )
            report(
                "5b-timeout-rollback",
                ok5b,
                f"rolled={rolled} turn_err={turn_err} a_next={a_next!r} "
                f"hist_len={len(session5b.history)}",
            )
            end_session(session5b)

    # --- 5c: first-pass timeout formula ---
    # Empty-ish history: estimate small -> max(90, 60 + small) = 90
    hist_small = [ChatMessage(role="system", content="x" * 100)]
    est_small = prompt_size_estimate(hist_small)
    t_small = first_pass_timeout_seconds(hist_small, 90)
    # Large history: chars=200_000 -> estimate=50_000 -> 60+1000=1060 -> cap 450
    hist_large = [ChatMessage(role="user", content="y" * 200_000)]
    est_large = prompt_size_estimate(hist_large)
    t_large = first_pass_timeout_seconds(hist_large, 90)
    # Medium: chars=20_000 -> estimate=5000 -> 60+100=160 > 90
    hist_med = [ChatMessage(role="user", content="z" * 20_000)]
    t_med = first_pass_timeout_seconds(hist_med, 90)
    ok5c = (
        history_char_count(hist_small) == 100
        and est_small == 25.0
        and t_small == 90
        and est_large == 50_000.0
        and t_large == settings.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS
        and t_med == 160
    )
    report(
        "5c-timeout-formula",
        ok5c,
        f"t_small={t_small} t_med={t_med} t_large={t_large} "
        f"cap={settings.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS}",
    )

    # --- 6: cross-turn compression keeps latest per tool name ---
    # Build 3 turns with two web_research and two browser_observe results.
    hist6 = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="t1"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                _tool_call("wr1", "web_research", {"question": "q1"}),
                _tool_call("bo1", "browser_observe", {"looking_for": "one"}),
            ],
        ),
        ChatMessage(role="tool", content="web_research result ONE full", tool_call_id="wr1"),
        ChatMessage(role="tool", content="browser_observe result ONE full", tool_call_id="bo1"),
        ChatMessage(role="assistant", content="turn1 done"),
        ChatMessage(role="user", content="t2"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                _tool_call("wr2", "web_research", {"question": "q2"}),
                _tool_call("bo2", "browser_observe", {"looking_for": "two"}),
            ],
        ),
        ChatMessage(role="tool", content="web_research result TWO full", tool_call_id="wr2"),
        ChatMessage(role="tool", content="browser_observe result TWO full", tool_call_id="bo2"),
        ChatMessage(role="assistant", content="turn2 done"),
        ChatMessage(role="user", content="t3"),
    ]
    before_ids = [m.tool_call_id for m in hist6 if m.role == "tool"]
    before_n = len(hist6)
    compress_cross_turn_history(hist6)
    tools6 = [m for m in hist6 if m.role == "tool"]
    by_id = {m.tool_call_id: m.content for m in tools6}
    ok6 = (
        len(hist6) == before_n
        and [m.tool_call_id for m in tools6] == before_ids
        and by_id["wr1"] == CROSS_TURN_OMITTED
        and by_id["bo1"] == CROSS_TURN_OMITTED
        and by_id["wr2"] == "web_research result TWO full"
        and by_id["bo2"] == "browser_observe result TWO full"
    )
    report(
        "6",
        ok6,
        f"by_id={by_id!r}",
    )

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

    # --- 8: quote pairing + check against live-log answers/evidence ---
    def _load_finals_and_evidence(path: Path) -> tuple[list[str], list[str]]:
        finals: list[str] = []
        evidence: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("type") == "tool_call" and isinstance(rec.get("result"), str):
                evidence.append(rec["result"])
            if rec.get("type") == "final":
                # Prefer raw (pre-note); strip a wrongly appended note from shown.
                raw = rec.get("raw") or ""
                shown = rec.get("shown") or ""
                text = raw if raw else shown
                if text.endswith(QUOTE_CHECK_NOTE):
                    text = text[: -len(QUOTE_CHECK_NOTE)]
                finals.append(text)
        return finals, evidence

    reset_evidence()
    log_r1 = ROOT / "logs" / "agent_20261018-012408_10768.log"
    log_r2 = ROOT / "logs" / "agent_20261018-013010_16628.log"
    log_mis = ROOT / "logs" / "agent_20261018-004417_22344.log"
    finals_r1, evidence_r1 = _load_finals_and_evidence(log_r1)
    finals_r2, evidence_r2 = _load_finals_and_evidence(log_r2)
    _finals_mis, evidence_mis = _load_finals_and_evidence(log_mis)

    # Both runs' turn-1 answers and run 2's turn-2 -> NO note (no long quotes).
    out_r1_t1 = check_quotes_against_evidence(finals_r1[0], evidence=evidence_r1)
    out_r2_t1 = check_quotes_against_evidence(finals_r2[0], evidence=evidence_r2)
    out_r2_t2 = check_quotes_against_evidence(finals_r2[1], evidence=evidence_r2)
    ok8_short = (
        QUOTE_CHECK_NOTE not in out_r1_t1
        and QUOTE_CHECK_NOTE not in out_r2_t1
        and QUOTE_CHECK_NOTE not in out_r2_t2
    )
    report(
        "8a-no-long-quotes",
        ok8_short,
        f"r1t1_note={QUOTE_CHECK_NOTE in out_r1_t1} "
        f"r2t1_note={QUOTE_CHECK_NOTE in out_r2_t1} "
        f"r2t2_note={QUOTE_CHECK_NOTE in out_r2_t2}",
    )

    # Run 1 turn-2 Brennus quote is in evidence -> no note.
    out_brennus = check_quotes_against_evidence(finals_r1[1], evidence=evidence_r1)
    ok8_brennus = QUOTE_CHECK_NOTE not in out_brennus
    report(
        "8b-brennus-in-evidence",
        ok8_brennus,
        f"note_absent={ok8_brennus} answer_start={finals_r1[1][:60]!r}",
    )

    # Earlier misquote from 004417 log -> note.
    misquote = (
        'The first sentence of the Wikipedia article on ATP synthase is:\n\n'
        '**"ATP synthase is an enzyme that produces ATP (energy currency of '
        'cells) by combining ADP and inorganic phosphate (Pi)."**\n\n'
        "This is based on the content retrieved from the earlier web research "
        "results."
    )
    out_mis = check_quotes_against_evidence(misquote, evidence=evidence_mis)
    ok8_mis = QUOTE_CHECK_NOTE in out_mis
    report(
        "8c-misquote",
        ok8_mis,
        f"note_appended={ok8_mis} n_ev={len(evidence_mis)}",
    )

    # --- 9: /new clears evidence ---
    reset_evidence()
    from scripts.agent_loop import append_evidence

    append_evidence("some tool text")
    provider9 = ScriptedProvider(
        [ChatResponse(content="hi", finish_reason="stop", tool_calls=None)]
    )
    session9 = new_session(provider9)
    ok9 = get_evidence() == []
    report("9-evidence-clear", ok9, f"evidence={get_evidence()!r}")
    end_session(session9)

    # --- 10: stale refs within one step ---
    from agent.executor.executor import execute_tool_calls
    from agent.executor.guard import CallGuard as _CG

    reset_session()
    close_session()
    clicked: list[str] = []
    typed: list[str] = []

    def _fake_click(ref: int) -> str:
        clicked.append(str(ref))
        return "clicked ok"

    def _fake_type(ref: int, text: str, submit: bool = False) -> str:
        typed.append(text)
        return "typed ok"

    with patch.dict(
        TOOL_FUNCTIONS,
        {"browser_click": _fake_click, "browser_type": _fake_type},
    ):
        guard10 = _CG()
        batch = [
            _tool_call("c10", "browser_click", {"ref": 5}),
            _tool_call(
                "t10",
                "browser_type",
                {"ref": 3, "text": "ATP synthase", "submit": True},
            ),
        ]
        with answer_by_action({"browser_click": "yes", "browser_type": "browser_type"}):
            msgs = execute_tool_calls(batch, guard=guard10)
    skip = msgs[1].content
    ok10 = (
        clicked == ["5"]
        and typed == []
        and msgs[0].content == "clicked ok"
        and msgs[0].tool_call_id == "c10"
        and msgs[1].tool_call_id == "t10"
        and skip.startswith("NOT DONE: browser_type(")
        and "browser_type" in skip
        and "nothing was typed or submitted" in skip
        and "ref=3" in skip
        and "ATP synthase" in skip
        and "submit=true" in skip
    )
    # Guard must not have recorded the skipped type (identical type allowed later).
    blocked_later = guard10.check(
        "browser_type", {"ref": 3, "text": "ATP synthase", "submit": True}
    )
    ok10 = ok10 and blocked_later is None
    report(
        "10-stale-refs",
        ok10,
        f"clicked={clicked} typed={typed} m1={skip[:80]!r} "
        f"later_block={blocked_later!r}",
    )

    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
