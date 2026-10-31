"""Round 11 Part 1 — planner offline tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def test_needs_plan_phrases() -> None:
    from agent.planner import needs_plan

    # 6 hard/medium coding + file targets/guards (must plan)
    hard_true = [
        (
            "qa_h_code_cli",
            "Build a command-line expense tracker in Python: add an expense with amount, "
            "category and date; list expenses; show totals per category; store data in "
            "SQLite; include pytest tests; run the tests and show me they pass.",
        ),
        (
            "qa_h_multistep",
            "Combine the CSVs in C:/tmp/data, find the best and worst month by revenue, "
            "and write a summary.md in the same folder.",
        ),
        (
            "qa_m_organise",
            "Organise the folder C:/tmp/box into subfolders by file type. "
            "Move each file into an appropriate type folder.",
        ),
        (
            "qa_h_code_debug",
            "The tests in my_project fail. Find and fix the bugs in the project code, "
            "then run the tests. Do not modify the test files.",
        ),
        (
            "qa_h_code_website",
            "Make a single-page personal portfolio website (HTML+CSS+JS in one file) "
            "with a dark theme, a projects section and a contact form that validates "
            "email. Save it in the workspace.",
        ),
        (
            "qa_m_code_small",
            "Write a Python function that checks if a string is a palindrome, with tests, "
            "and run them.",
        ),
    ]
    # 6 easy / chat (must NOT plan)
    easy_false = [
        ("qa_e_greeting", "Hi, what can you do?"),
        ("qa_e_math", "What is 17% of 2,350?"),
        ("qa_e_list_folder", "List the files in C:/tmp with their sizes."),
        ("qa_e_read_txt", "What does notes.txt say about the meeting time?"),
        ("qa_e_memory", "Remember my favourite colour is teal."),
        ("qa_m_web_fact", "What is the current population of Malaysia according to recent sources?"),
    ]
    # 8 more mixed
    extra = [
        ("and_then", "Create a folder and then move report.pdf into it.", True),
        ("chat_short", "Hello!", False),
        ("single_read", "Read the README.", False),
        ("two_verbs", "Create a file and write hello into it.", True),
        ("app_word", "Scaffold a small app with a settings page.", True),
        ("project_word", "Start a new project for invoice parsing.", True),
        ("long_one_verb", "x" * 100 + " please save the final report to disk as report.txt when ready.", True),
        ("thanks", "Thanks!", False),
    ]

    for name, prompt in hard_true:
        _check(f"needs_plan_true:{name}", needs_plan(prompt) is True, prompt[:60])
    for name, prompt in easy_false:
        _check(f"needs_plan_false:{name}", needs_plan(prompt) is False, prompt[:60])
    for name, prompt, expect in extra:
        _check(f"needs_plan_{name}", needs_plan(prompt) is expect, prompt[:60])


def test_json_parse_and_repair() -> None:
    from agent.planner import parse_plan_json

    good = parse_plan_json(
        'Here:\n```json\n{"steps":[{"step":"a","tool_hint":"none","done_when":"x"}]}\n```'
    )
    _check("parse_fenced", good is not None and len(good["steps"]) == 1, repr(good))

    trailing = parse_plan_json(
        '{"steps":[{"step":"a","tool_hint":"ws_write","done_when":"file exists",},]}'
    )
    _check("parse_trailing_comma", trailing is not None, repr(trailing))

    bad = parse_plan_json("no json here")
    _check("parse_none", bad is None)

    over = {
        "steps": [
            {"step": f"s{i}", "tool_hint": "none", "done_when": "d"} for i in range(12)
        ]
    }
    capped = parse_plan_json(json.dumps(over))
    _check("cap_8", capped is not None and len(capped["steps"]) == 8, repr(capped))


def test_cache_safe_local_prompt() -> None:
    """message 0 and tools are byte-identical to a normal turn."""
    from agent.planner import PLANNING_INSTRUCTION, plan_via_local
    from llm.base import ChatMessage, ChatResponse
    from tools.registry import active_tool_schemas

    tools_normal = active_tool_schemas()
    tools_bytes = json.dumps(tools_normal, sort_keys=True, separators=(",", ":"))

    system0 = "SYSTEM_PROMPT_CACHE_PREFIX_v1"
    history = [
        ChatMessage(role="system", content=system0),
        ChatMessage(role="user", content="Build an app and then run the tests."),
    ]
    captured: dict = {}

    class FakeProv:
        def chat(self, messages, tools=None, **kwargs):
            captured["msg0"] = messages[0].content
            captured["tools"] = json.dumps(tools or [], sort_keys=True, separators=(",", ":"))
            captured["n"] = len(messages)
            captured["last"] = messages[-1].content
            captured["thinking"] = kwargs.get("enable_thinking")
            return ChatResponse(
                content=json.dumps(
                    {
                        "steps": [
                            {
                                "step": "scaffold",
                                "tool_hint": "ws_write",
                                "done_when": "files exist",
                            }
                        ]
                    }
                )
            )

    plan = plan_via_local(FakeProv(), history, tools=tools_normal)
    _check("plan_parsed", plan is not None and plan["steps"][0]["step"] == "scaffold")
    _check("msg0_identical", captured.get("msg0") == system0, repr(captured.get("msg0")))
    _check(
        "tools_byte_identical",
        captured.get("tools") == tools_bytes,
        f"len {len(captured.get('tools') or '')} vs {len(tools_bytes)}",
    )
    _check(
        "planning_instruction_appended",
        captured.get("last") == PLANNING_INSTRUCTION,
        repr(captured.get("last"))[:80],
    )
    _check("thinking_on", captured.get("thinking") is True)
    # Instruction removed after plan
    _check(
        "instruction_removed",
        not any(m.content == PLANNING_INSTRUCTION for m in history),
        str(len(history)),
    )


def test_finish_guard_once() -> None:
    from agent import planner as P

    P.reset_plan_turn()
    P._emit_plan(
        {"steps": [{"step": "a", "tool_hint": "none", "done_when": "x"}]},
        source="local",
    )
    _check("should_fire_first", P.should_run_finish_guard() is True)
    P.mark_finish_guard_fired()
    _check("should_not_fire_second", P.should_run_finish_guard() is False)
    msg = P.finish_guard_message()
    _check("guard_mentions_done_when", "done_when" in (msg.content or ""))


def test_no_plan_for_easy() -> None:
    from agent.planner import maybe_attach_plan, needs_plan
    from llm.base import ChatMessage

    os.environ["MINIAI_PLANNER"] = "local"
    try:
        _check("easy_needs_false", needs_plan("Hi, what can you do?") is False)
        history = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="Hi, what can you do?"),
        ]

        class Boom:
            def chat(self, *a, **k):
                raise AssertionError("planner must not call model for easy Q")

        out = maybe_attach_plan(Boom(), history, "Hi, what can you do?", tools=[])
        _check("easy_no_attach", out is None)
        _check("history_unchanged", len(history) == 2)
    finally:
        del os.environ["MINIAI_PLANNER"]


def test_groq_fallback_note() -> None:
    from agent.planner import plan_via_groq
    from security.groq_key import remove_key

    remove_key()
    plan, note = plan_via_groq("Build an app and then test it")
    _check("no_key_fallback", plan is None and "local planner" in note.lower(), note)


def main() -> None:
    test_needs_plan_phrases()
    test_json_parse_and_repair()
    test_cache_safe_local_prompt()
    test_finish_guard_once()
    test_no_plan_for_easy()
    test_groq_fallback_note()
    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
