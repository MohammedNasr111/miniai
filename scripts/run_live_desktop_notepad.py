"""Live chat: open Notepad with a note, ask what it says (trust=session)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.support import answer_by_action

from scripts.agent_loop import _require_lemonade
from scripts.chat import end_session, new_session, run_user_turn
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session
from tools.browser.browser_tools import close_session

NOTE = "The kettle is on the second shelf."
PROMPT = (
    "There is a Notepad window open on this computer with a short note. "
    "Use desktop_list_windows and desktop_read_window to read it. "
    "What does that note say?"
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _require_lemonade()
    reset_session()
    close_session()
    tmp = Path(tempfile.mkdtemp(prefix="miniai_live8a_"))
    path = tmp / "miniai_live8a_note.txt"
    path.write_text(NOTE + "\n", encoding="utf-8")
    proc = subprocess.Popen(["notepad.exe", str(path)])
    time.sleep(1.5)
    provider = LemonadeProvider()
    session = new_session(provider)
    mapping = {"desktop_read_window": "session"}
    answer = ""
    try:
        with answer_by_action(mapping) as prompt_log:
            print(f"You> {PROMPT}")
            answer = run_user_turn(session, PROMPT)
            print(f"Assistant> {answer}")
        print("\n=== PROMPT LOG ===")
        for action, prompt, ans in prompt_log:
            print(f"Action={action!r} prompt={prompt!r} answer={ans!r}")
        transcript = str(session.transcript.path) if session.transcript else None
        print(f"TRANSCRIPT={transcript}")
        print(f"NOTE_PRESENT_IN_ANSWER={NOTE.lower() in answer.lower()}")
    finally:
        end_session(session)
        close_session()
        try:
            proc.kill()
        except OSError:
            pass


if __name__ == "__main__":
    main()
