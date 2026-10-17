"""Scripted crash recovery: guard forgets browser tools after a close."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

from tests.support import answer_by_action

from agent.executor.executor import execute_tool_calls
from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from security.gate import reset_session
from tools.browser import browser_tools
from tools.browser.browser_tools import close_session
from tools.browser.session import BrowserSession

FAILURES: list[str] = []
URL = "https://example.com"


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _transcript_events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    reset_session()
    close_session()
    tmp = tempfile.mkdtemp(prefix="miniai_crash_")
    transcript = Transcript()
    guard = CallGuard()

    def _launch():
        return BrowserSession(headless=True, profile_dir=tmp)

    try:
        with patch.object(browser_tools, "_launch_session", side_effect=_launch):
            with answer_by_action({"browser_open": "yes"}) as prompt_log:
                # 1. browser_open ok
                r1 = execute_tool_calls(
                    [_call("1", "browser_open", {"url": URL})],
                    guard=guard,
                    transcript=transcript,
                )
                open1_ok = (
                    r1[0].content
                    and "Error:" not in r1[0].content[:20]
                    and "example" in r1[0].content.lower()
                )
                report("1", bool(open1_ok), f"len={len(r1[0].content)}")

                # 2. Close browser from the test
                session = browser_tools._session
                assert session is not None
                session.context.close()
                report("2", not session.is_alive(), f"alive={session.is_alive()}")

                # 3. browser_observe -> closed unexpectedly
                r3 = execute_tool_calls(
                    [_call("3", "browser_observe", {})],
                    guard=guard,
                    transcript=transcript,
                )
                closed_msg = "The browser closed unexpectedly" in r3[0].content
                report("3", closed_msg, f"content={r3[0].content!r}")

                # 4. identical browser_open must RUN (not blocked)
                r4 = execute_tool_calls(
                    [_call("4", "browser_open", {"url": URL})],
                    guard=guard,
                    transcript=transcript,
                )
                reopen_ok = (
                    "Blocked duplicate call" not in r4[0].content
                    and "Error:" not in r4[0].content[:20]
                    and browser_tools._session is not None
                    and browser_tools._session.is_alive()
                )
                report(
                    "4",
                    reopen_ok,
                    f"dup_blocked={'Blocked duplicate call' in r4[0].content} "
                    f"alive={browser_tools._session is not None and browser_tools._session.is_alive()}",
                )

                # 5. browser_observe -> Example Domain
                r5 = execute_tool_calls(
                    [_call("5", "browser_observe", {})],
                    guard=guard,
                    transcript=transcript,
                )
                observe_ok = (
                    "Blocked duplicate call" not in r5[0].content
                    and "Example Domain" in r5[0].content
                )
                report(
                    "5",
                    observe_ok,
                    f"has_title={'Example Domain' in r5[0].content}",
                )

            # 6. transcript has browser_event close entries
            events = _transcript_events(Path(transcript.path))
            browser_events = [e for e in events if e.get("type") == "browser_event"]
            objects = {e.get("object") for e in browser_events}
            report(
                "6",
                len(browser_events) >= 1 and bool(objects & {"page", "context"}),
                f"n={len(browser_events)} objects={objects!r} events={browser_events!r}",
            )

            # 7. denied open then identical retry still blocked
            reset_session()
            deny_guard = CallGuard()
            with answer_by_action({"browser_open": "no"}):
                r7a = execute_tool_calls(
                    [_call("7a", "browser_open", {"url": URL})],
                    guard=deny_guard,
                    transcript=transcript,
                )
            r7b = execute_tool_calls(
                [_call("7b", "browser_open", {"url": URL})],
                guard=deny_guard,
                transcript=transcript,
            )
            denied_ok = (
                r7a[0].content.startswith("Denied by user:")
                and "Blocked duplicate call" in r7b[0].content
            )
            report(
                "7",
                denied_ok,
                f"denied={r7a[0].content[:40]!r} blocked={'Blocked' in r7b[0].content}",
            )
            print(f"PROMPT_LOG={prompt_log!r}")
    finally:
        close_session()
        transcript.close()
        reset_session()

    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    print(f"Transcript: {transcript.path}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
