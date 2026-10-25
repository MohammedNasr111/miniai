"""Offline tests for Round 6 Part 2 coding-loop changes."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from llm.base import ChatMessage  # noqa: E402
from security.gate import Tier, reset_session  # noqa: E402
from tools.code.paths import workspace_dir  # noqa: E402
from tools.code.project_discover import (  # noqa: E402
    ensure_task_slug_folder,
    infer_test_target,
    list_project_candidates,
    slugify,
    ws_find_project,
)
from tools.code.pytest_summary import parse_pytest_summary  # noqa: E402
from tools.code.workspace_tools import CODING_TOOLS, maybe_auto_run_tests  # noqa: E402
from tools.registry import TOOL_FUNCTIONS, TOOL_TIERS  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


PASS_OUT = """
..                                                                       [100%]
============================== 2 passed in 0.05s ===============================
"""

FAIL_OUT = """
F.                                                                       [100%]
=================================== FAILURES ===================================
_________________________________ test_totals __________________________________
tests/test_app.py:12: in test_totals
    assert got == 10
E   assert 7 == 10
=========================== short test summary info ============================
FAILED tests/test_app.py::test_totals - assert 7 == 10
========================= 1 failed, 1 passed in 0.08s ==========================
"""

ERROR_OUT = """
E                                                                        [100%]
==================================== ERRORS ====================================
______________________ ERROR at setup of test_broken ___________________________
tests/test_broken.py:5: in test_broken
    raise RuntimeError("boom")
E   RuntimeError: boom
=========================== short test summary info ============================
ERROR tests/test_broken.py::test_broken - RuntimeError: boom
============================== 1 error in 0.04s ================================
"""

COLLECT_OUT = """
======= ERRORS ========
________________ ERROR collecting tests/test_bad.py ________________
ImportError: cannot import name 'missing'
===== 1 error in 0.02s =====
"""


def main() -> None:
    reset_session()

    # --- pytest summary parser ---
    s_pass = parse_pytest_summary(PASS_OUT)
    _check("parser_pass", "2 passed" in s_pass and "fail" not in s_pass.lower(), s_pass)

    s_fail = parse_pytest_summary(FAIL_OUT)
    _check(
        "parser_fail",
        "failing" in s_fail.lower()
        and "test_totals" in s_fail
        and "assert 7 == 10" in s_fail
        and len(s_fail) <= 1500,
        s_fail,
    )

    s_err = parse_pytest_summary(ERROR_OUT)
    _check("parser_error", "error" in s_err.lower() and "test_broken" in s_err, s_err)

    s_col = parse_pytest_summary(COLLECT_OUT)
    _check(
        "parser_collect",
        "collection" in s_col.lower() or "error" in s_col.lower(),
        s_col,
    )

    wrapped = (
        "Untrusted program output follows.\n"
        "<<<BEGIN UNTRUSTED CODE OUTPUT>>>\n"
        f"exit_code: 1\n--- stdout ---\n{FAIL_OUT}\n--- stderr ---\n(empty)\n"
        "<<<END UNTRUSTED CODE OUTPUT>>>"
    )
    s_wrap = parse_pytest_summary(wrapped)
    _check("parser_wrapped", "test_totals" in s_wrap, s_wrap)

    # --- ws_find_project ranking ---
    ws = workspace_dir()
    # Clean leftover noise lightly: only create our fixtures
    alpha = ws / "alpha_app"
    alpha.mkdir(parents=True, exist_ok=True)
    (alpha / "main.py").write_text("x=1\n", encoding="utf-8")
    (alpha / "tests").mkdir(exist_ok=True)
    (alpha / "tests" / "test_main.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    beta = ws / "beta_other"
    beta.mkdir(parents=True, exist_ok=True)
    (beta / "app.py").write_text("y=2\n", encoding="utf-8")
    (beta / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    out = ws_find_project(hint="alpha")
    _check("find_lists", "alpha_app" in out, out[:300])
    cands = list_project_candidates("alpha")
    _check(
        "find_rank",
        cands and "alpha" in cands[0]["path"],
        str([c["path"] for c in cands[:3]]),
    )
    _check(
        "find_meta",
        cands and "file_count" in cands[0] and "newest_mtime" in cands[0],
        str(cands[0]) if cands else "",
    )

    # --- slug folder creation (unique name so prior workspace noise cannot match) ---
    uniq = f"zorpwidget{int(__import__('time').time()) % 100000}"
    slug = ensure_task_slug_folder(
        f"Please build a {uniq} cli tool with pytest"
    )
    _check("slug_created", bool(slug) and (ws / slug).is_dir(), str(slug))
    _check("slug_words", slug is not None and "zorpwidget" in (slug or ""), str(slug))
    # Debug/fix existing code must not create a new slug
    buggy = ws / "buggy"
    buggy.mkdir(exist_ok=True)
    (buggy / "mathy.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
    (ws / "tests").mkdir(exist_ok=True)
    (ws / "tests" / "test_mathy.py").write_text(
        "from buggy.mathy import add\ndef test_add():\n assert add(1,2)==3\n",
        encoding="utf-8",
    )
    no_slug = ensure_task_slug_folder("The tests in the workspace fail — please debug mathy")
    _check("slug_skip_existing", no_slug is None, str(no_slug))

    # --- infer_test_target ---
    tgt2 = infer_test_target(["buggy/mathy.py"])
    _check("infer_tests_root", tgt2 == "tests", str(tgt2))
    tgt3 = infer_test_target(["alpha_app/main.py"])
    _check("infer_tests_nested", tgt3 == "alpha_app/tests", str(tgt3))

    # --- auto-test fires once per round ---
    calls = {"n": 0}

    def _fake_run_tests(path="tests", timeout_s=60):
        calls["n"] += 1
        return FAIL_OUT

    with patch(
        "tools.code.workspace_tools.run_tests", side_effect=_fake_run_tests
    ):
        # maybe_auto_run_tests imports run_tests from same module — patch there
        pass

    with patch(
        "tools.code.workspace_tools.run_tests", side_effect=_fake_run_tests
    ) as _:
        # Re-import path used inside maybe_auto_run_tests is local run_tests
        msg1 = maybe_auto_run_tests(["alpha_app/main.py"])
        msg2 = maybe_auto_run_tests(["alpha_app/main.py"])
    _check("auto_fires", msg1 is not None and "test_totals" in (msg1 or ""), str(msg1))
    _check("auto_twice_ok", calls["n"] == 2, f"n={calls['n']}")  # helper itself each call

    # Agent loop: auto-test once per model round
    from scripts.agent_loop import run_tool_rounds

    auto_calls = {"n": 0}

    def _ex(tool_calls, **kwargs):
        return [
            ChatMessage(
                role="tool",
                content="Wrote alpha_app/main.py (3 bytes). Commit abc.",
                tool_call_id="c1",
            )
        ]

    def _provider():
        state = {"i": 0}

        class P:
            model = "fake"
            timeout = 30

            def chat(self, *a, **k):
                state["i"] += 1
                if state["i"] <= 2:
                    tc = {
                        "id": f"c{state['i']}",
                        "type": "function",
                        "function": {
                            "name": "ws_write",
                            "arguments": json.dumps(
                                {"path": "alpha_app/main.py", "content": "x=1\n"}
                            ),
                        },
                    }
                    return MagicMock(content="", tool_calls=[tc])
                return MagicMock(content="done", tool_calls=None)

        return P()

    def _auto(paths):
        auto_calls["n"] += 1
        return f"[Auto-test tests] Tests: 1 failing: test_totals — assert 7 == 10"

    with patch("scripts.agent_loop.execute_tool_calls", side_effect=_ex), patch(
        "tools.code.workspace_tools.maybe_auto_run_tests", side_effect=_auto
    ):
        hist = [ChatMessage(role="user", content="fix alpha")]
        run_tool_rounds(_provider(), hist, MagicMock())
    _check(
        "auto_once_per_round",
        auto_calls["n"] == 2,  # two model rounds with ws_write each
        f"n={auto_calls['n']}",
    )
    # Ensure each round only one auto (already true: one ws_write per round)

    # --- coding round cap 16 ---
    with patch("scripts.agent_loop.execute_tool_calls") as ex:
        ex.return_value = [
            ChatMessage(role="tool", content="ok", tool_call_id="c1")
        ]
        state = {"i": 0}

        class P16:
            model = "fake"
            timeout = 30

            def chat(self, *a, **k):
                state["i"] += 1
                if state["i"] <= 18:
                    tc = {
                        "id": f"c{state['i']}",
                        "type": "function",
                        "function": {
                            "name": "ws_list",
                            "arguments": json.dumps({"path": "."}),
                        },
                    }
                    return MagicMock(content="", tool_calls=[tc])
                return MagicMock(content="done", tool_calls=None)

        r = run_tool_rounds(P16(), [ChatMessage(role="user", content="code")], MagicMock())
        _check(
            "cap_16",
            "Stopped after 16 tool rounds" in (r.content or ""),
            (r.content or "")[:120],
        )

    # registry
    _check(
        "registry",
        TOOL_FUNCTIONS.get("ws_find_project") is ws_find_project
        and TOOL_TIERS.get("ws_find_project") == Tier.AUTO_ALLOW
        and "ws_find_project" in CODING_TOOLS
        and set(TOOL_TIERS) == set(TOOL_FUNCTIONS),
        "",
    )
    _check("slugify", slugify("Hello World!!") == "hello-world", slugify("Hello World!!"))

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
