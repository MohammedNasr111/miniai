"""Live Stage 9b: word-count function + pytest until green."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from tests.support import answer_by_action

from scripts.agent_loop import _require_lemonade
from scripts.chat import end_session, new_session, run_user_turn
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session
from tools.code.paths import workspace_dir
from tools.code.runner import run_argv
from tools.browser.browser_tools import close_session

PROMPT = (
    "In the workspace under the folder wordcount_demo, write a Python "
    "function that counts the words in a string (module wordcount.py), "
    "plus pytest tests for it under wordcount_demo/tests, and run the "
    "tests with run_tests until they pass."
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _require_lemonade()
    reset_session()
    close_session()
    # Isolate from earlier unit-test fixtures in the workspace.
    demo = workspace_dir() / "wordcount_demo"
    if demo.exists():
        import shutil

        shutil.rmtree(demo)
    provider = LemonadeProvider()
    session = new_session(provider)
    mapping = {
        "run_file": "yes",
        "run_tests": "yes",
        "run_code": "yes",
        "workspace_import": "yes",
        "workspace_export": "yes",
        "workspace_restore": "yes",
        "install_package": "install_package",
    }
    started = time.perf_counter()
    answer = ""
    prompt_log: list = []
    try:
        with answer_by_action(mapping, default="no") as prompt_log:
            print(f"\n=== LIVE CODING ===\nYou> {PROMPT}")
            answer = run_user_turn(session, PROMPT)
            print(f"Assistant> {answer}")
        wall = time.perf_counter() - started
        transcript_path = (
            str(session.transcript.path) if session.transcript else None
        )
        rounds = session.transcript.rounds if session.transcript else None
        print(f"\nTranscript: {transcript_path}")
        print(f"rounds={rounds}")
        print(f"wall_clock_sec={wall:.1f}")
        print("\n=== PROMPT LOG ===")
        for action, prompt, ans in prompt_log:
            print(f"Action={action!r} answer={ans!r} prompt_len={len(prompt)}")

        tool_calls: list[dict] = []
        if transcript_path and Path(transcript_path).is_file():
            for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "tool_call":
                    tool_calls.append(ev)
        print(f"\n=== TOOL CALLS ({len(tool_calls)}) ===")
        for ev in tool_calls:
            print(f"  {ev.get('name')} outcome={ev.get('outcome')}")

        # Independent verify: prefer wordcount_demo, else workspace tests/ + wordcount.py
        ws = workspace_dir()
        candidates = []
        if (ws / "wordcount_demo").is_dir():
            candidates.append(ws / "wordcount_demo")
        if (ws / "tests" / "test_wordcount.py").is_file():
            candidates.append(ws / "tests")
        verify_ok = False
        for target in candidates:
            result = run_argv(
                ["-m", "pytest", str(target), "-q", "--tb=line"],
                timeout_s=60,
                script_path=str(target),
                cwd=ws,
            )
            verify_out = (result.stdout or "") + (result.stderr or "")
            print(f"\n=== INDEPENDENT pytest {target} exit={result.exit_code} ===")
            print(verify_out[-2000:])
            if result.exit_code == 0:
                verify_ok = True
                break
        if not candidates:
            print("\n=== INDEPENDENT pytest: no wordcount test paths found ===")
        print(f"tests_ended_passing_in_chat={('pass' in answer.lower())}")
        print(f"independent_pytest_ok={verify_ok}")
        print(f"LIVE_OK={verify_ok}")
        sys.exit(0 if verify_ok else 1)
    finally:
        end_session(session)


if __name__ == "__main__":
    main()
