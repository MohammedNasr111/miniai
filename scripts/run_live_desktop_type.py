"""Live chat: type into an empty Notepad via desktop_set_text."""

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
from security.app_trust import trusted_apps_path
from security.gate import reset_session
from tools.browser.browser_tools import close_session
from tools.desktop.desktop_tools import (
    clear_window_map,
    desktop_list_windows,
    desktop_read_window,
)
from tools.desktop.task_grant import clear_task_grant
from tools.web.untrusted import BEGIN_MARKER

TARGET = "Meeting at 3pm"
PROMPT = (
    "In the Notepad window, type 'Meeting at 3pm' at the top. "
    "Use desktop_list_windows, desktop_begin_task, desktop_read_window, "
    "and desktop_set_text. Do not save the file."
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _require_lemonade()
    reset_session()
    close_session()
    clear_task_grant()
    clear_window_map()
    # Prefill trust so the live run focuses on begin_task / set_text.
    path = trusted_apps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"notepad.exe": true}\n', encoding="utf-8")

    tmp = Path(tempfile.mkdtemp(prefix="miniai_live8b_"))
    note = tmp / "miniai_live8b_empty.txt"
    note.write_text("", encoding="utf-8")
    proc = subprocess.Popen(["notepad.exe", str(note)])
    time.sleep(1.5)

    provider = LemonadeProvider()
    session = new_session(provider)
    mapping = {
        # List/read taint the session, so begin_task needs the typed name.
        "desktop_begin_task": "desktop_begin_task",
        "desktop_read_window": "session",
        "desktop_press": "desktop_press",
        "desktop_set_text": "desktop_set_text",
    }
    answer = ""
    try:
        with answer_by_action(mapping) as prompt_log:
            print(f"You> {PROMPT}")
            answer = run_user_turn(session, PROMPT)
            print(f"Assistant> {answer}")
        print("\n=== PROMPT LOG ===")
        for action, prompt, ans in prompt_log:
            print(f"Action={action!r} answer={ans!r}")
        # Independent verify: re-list and read Notepad in code.
        clear_task_grant()
        listing = desktop_list_windows()
        wref = None
        for line in listing.splitlines():
            if "miniai_live8b_empty" in line.lower() and "[w" in line:
                wref = line[line.index("[") + 1 : line.index("]")]
                break
        verified = ""
        if wref:
            verified = desktop_read_window(wref)
        print(f"VERIFY_BEGIN={BEGIN_MARKER in verified}")
        print(f"VERIFY_HAS_TARGET={TARGET in verified}")
        print(f"TRANSCRIPT={session.transcript.path if session.transcript else None}")
        print(f"ANSWER_MENTIONS_TARGET={TARGET.lower() in answer.lower()}")
    finally:
        end_session(session)
        close_session()
        clear_task_grant()
        try:
            proc.kill()
        except OSError:
            pass


if __name__ == "__main__":
    main()
