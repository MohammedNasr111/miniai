"""Live two-turn chat: open/search Wikipedia, then ask for first sentence."""

from __future__ import annotations

import sys

from tests.support import answer_by_action

from scripts.agent_loop import _require_lemonade
from scripts.chat import end_session, new_session, run_user_turn
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session
from tools.browser.browser_tools import close_session

TURN1 = (
    "Open https://en.wikipedia.org in the browser and search for ATP synthase."
)
TURN2 = "What is the first sentence of that article?"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _require_lemonade()
    reset_session()
    close_session()
    provider = LemonadeProvider()
    session = new_session(provider)
    mapping = {
        "browser_open": "yes",
        "browser_type": "browser_type",
        "browser_click": "yes",
    }
    try:
        with answer_by_action(mapping) as prompt_log:
            print(f"\n=== TURN 1 ===\nYou> {TURN1}")
            a1 = run_user_turn(session, TURN1)
            print(f"Assistant> {a1}")
            print(f"\n=== TURN 2 ===\nYou> {TURN2}")
            a2 = run_user_turn(session, TURN2)
            print(f"Assistant> {a2}")
        print("\n=== PROMPT LOG ===")
        for action, prompt, answer in prompt_log:
            print(f"Action={action!r} answer={answer!r}")
        # Did turn 2 call browser_open?
        opens = [
            m
            for m in session.history
            if m.role == "assistant"
            and m.tool_calls
            and any(
                (c.get("function") or {}).get("name") == "browser_open"
                for c in m.tool_calls
            )
        ]
        # Count browser_open tool results in history (full session)
        open_calls = 0
        for m in session.history:
            if m.role == "assistant" and m.tool_calls:
                for c in m.tool_calls:
                    if (c.get("function") or {}).get("name") == "browser_open":
                        open_calls += 1
        print(f"browser_open_calls_in_session={open_calls}")
        print(f"Transcript: {session.transcript.path if session.transcript else None}")
        print(f"TURN1_ANSWER={a1!r}")
        print(f"TURN2_ANSWER={a2!r}")
        # Success: exactly one browser_open (turn 1), turn 2 answered
        ok = open_calls == 1 and bool(a2.strip())
        print(f"LIVE_OK={ok}")
        sys.exit(0 if ok else 1)
    finally:
        end_session(session)


if __name__ == "__main__":
    main()
