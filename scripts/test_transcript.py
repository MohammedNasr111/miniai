"""Offline checks for transcripts and final-answer cleanup. No LLM."""

import json
import sys
from unittest.mock import patch

from agent.executor.executor import execute_tool_calls
from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from scripts.agent_loop import clean_final_answer
from security.gate import PermissionDenied
from tools.registry import TOOL_FUNCTIONS
from tools.web.untrusted import BEGIN_MARKER, END_MARKER

FAILURES = 0
SECRET = "tvly-FAKEKEY-DO-NOT-LEAK"

# Verbatim Q1 A run 1 answer from logs/eval_research_answers_20261011-180819.log.
Q1_A_RUN_1 = (
    "The latest stable version of Python, as of October 11, 2026, is "
    "**Python 3.15.0**, released on October 9, 2026. This information is "
    "confirmed by the official Python download page, which lists 3.15.0 as "
    "the most recent active release. Earlier versions like 3.14.8 "
    "(September 30, 2026) are maintenance updates for the 3.14 series, but "
    "3.15.0 is the latest major stable version.\n"
    "\n"
    "Source: [Python Downloads Page](https://www.python.org/downloads/)  \n"
    "<<<BEGIN UNTRUSTED WEB CONTENT>>>  \n"
    "[source 4, chunk 0, similarity 0.725]  \n"
    "Active Python releases:  \n"
    "- Python 3.15.0 Oct. 9, 2026  \n"
    "- Python 3.14.8 Sept. 30, 2026  \n"
    "...  \n"
    "<<<END UNTRUSTED WEB CONTENT>>>"
)


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")


def _markers_gone(text: str) -> bool:
    return BEGIN_MARKER not in text and END_MARKER not in text


def test_1() -> None:
    cleaned = clean_final_answer(Q1_A_RUN_1)
    _check(
        "1a",
        _markers_gone(cleaned) and "3.15.0" in cleaned and "similarity 0.725" not in cleaned,
        f"len={len(cleaned)} has_3.15.0={'3.15.0' in cleaned}",
    )
    two = (
        "before\n"
        f"{BEGIN_MARKER}\nsecret one\n{END_MARKER}\n"
        "middle\n"
        f"{BEGIN_MARKER}\nsecret two\n{END_MARKER}\n"
        "after"
    )
    cleaned_two = clean_final_answer(two)
    _check(
        "1b",
        _markers_gone(cleaned_two)
        and "secret one" not in cleaned_two
        and "secret two" not in cleaned_two
        and "before" in cleaned_two
        and "middle" in cleaned_two
        and "after" in cleaned_two,
        repr(cleaned_two),
    )
    unclosed = f"keep this\n{BEGIN_MARKER}\nquoted page that stays"
    cleaned_open = clean_final_answer(unclosed)
    _check(
        "1c",
        _markers_gone(cleaned_open)
        and "keep this" in cleaned_open
        and "quoted page that stays" in cleaned_open,
        repr(cleaned_open),
    )
    plain = "No markers here. Leave this alone."
    _check("1d", clean_final_answer(plain) == plain, repr(clean_final_answer(plain)))
    padded = f"  {plain}  "
    _check("1d-strip", clean_final_answer(padded) == plain, repr(clean_final_answer(padded)))
    collapsed = clean_final_answer("a\n\n\n\n\nb")
    _check("1-collapse", collapsed == "a\n\n\nb", repr(collapsed))


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def test_2_and_3() -> Transcript:
    long_result = "Z" * 1000
    saved = {
        "write_file": TOOL_FUNCTIONS["write_file"],
        "delete_file": TOOL_FUNCTIONS["delete_file"],
        "read_file": TOOL_FUNCTIONS["read_file"],
    }
    transcript = Transcript()
    try:
        def ok_write(**kwargs):
            return long_result

        def deny_delete(**kwargs):
            raise PermissionDenied("User denied: delete_file")

        def boom_read(**kwargs):
            raise RuntimeError("boom")

        TOOL_FUNCTIONS["write_file"] = ok_write
        TOOL_FUNCTIONS["delete_file"] = deny_delete
        TOOL_FUNCTIONS["read_file"] = boom_read
        guard = CallGuard()
        write_args = {"path": "notes.txt", "content": "hello"}
        ok_messages = execute_tool_calls(
            [_call("c1", "write_file", write_args)],
            guard=guard,
            transcript=transcript,
        )
        blocked_messages = execute_tool_calls(
            [_call("c2", "write_file", write_args)],
            guard=guard,
            transcript=transcript,
        )
        denied_messages = execute_tool_calls(
            [_call("c3", "delete_file", {"path": "notes.txt"})],
            guard=guard,
            transcript=transcript,
        )
        error_messages = execute_tool_calls(
            [_call("c4", "read_file", {"path": "notes.txt"})],
            guard=guard,
            transcript=transcript,
        )
    finally:
        TOOL_FUNCTIONS.update(saved)
        transcript.close()

    text = transcript.path.read_text(encoding="utf-8")
    lines = text.splitlines()
    events = []
    parse_ok = True
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            parse_ok = False
    _check("3", parse_ok and len(lines) == 4 and all(line.strip() for line in lines), f"lines={len(lines)}")
    outcomes = [event.get("outcome") for event in events]
    full_ok = (
        len(events) == 4
        and outcomes == ["ok", "blocked", "denied", "error"]
        and events[0]["result"] == ok_messages[0].content
        and events[0]["result"] == long_result
        and len(events[0]["result"]) == 1000
        and events[1]["result"] == blocked_messages[0].content
        and events[2]["result"] == denied_messages[0].content
        and events[3]["result"] == error_messages[0].content
        and events[0]["name"] == "write_file"
        and events[2]["result"].startswith("Denied by user:")
        and events[3]["result"] == "Error: boom"
    )
    _check("2", full_ok, f"outcomes={outcomes} ok_len={len(events[0]['result']) if events else 0}")
    return transcript


def test_4(transcript: Transcript) -> None:
    text = transcript.path.read_text(encoding="utf-8")
    _check("4", SECRET not in text, f"secret_present={SECRET in text} path={transcript.path}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    test_1()
    with patch("config.settings.TAVILY_API_KEY", SECRET):
        transcript = test_2_and_3()
        test_4(transcript)
    if FAILURES:
        print(f"\n{FAILURES} check(s) failed.")
        sys.exit(1)
    print("\nAll transcript checks passed.")


if __name__ == "__main__":
    main()
