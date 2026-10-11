"""Offline checks for session taint in the permission gate. No LLM."""

import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

from agent.executor.executor import execute_tool_calls
from security.gate import (
    PermissionDenied,
    Tier,
    check_permission,
    is_tainted,
    mark_untrusted,
    reset_session,
)
from tools.registry import TOOL_FUNCTIONS

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    print(f"{status}: {name} - {detail}")


def _call(action: str, tier: Tier, answer: str, description: str = "desc"):
    def _input(prompt=""):
        print(prompt, end="")
        return answer

    buf = io.StringIO()
    with patch("builtins.input", side_effect=_input), redirect_stdout(buf):
        check_permission(action, tier, description)
    return buf.getvalue()


def test_a() -> None:
    reset_session()
    try:
        text = _call("write_file", Tier.CONFIRM, "yes")
        ok = "WARNING" not in text and "Allow? [yes/no]:" in text and not is_tainted()
        detail = "approved, no banner"
    except PermissionDenied as exc:
        ok = False
        detail = str(exc)
    _check("a", ok, detail)


def test_b() -> None:
    reset_session()
    mark_untrusted("fetch_url")
    try:
        _call("write_file", Tier.CONFIRM, "yes")
        ok = False
        detail = "approved on yes"
    except PermissionDenied as exc:
        ok = "typed confirmation was required" in str(exc).lower()
        detail = str(exc)
    _check("b", ok, detail)


def test_c() -> None:
    reset_session()
    mark_untrusted("fetch_url")
    try:
        text = _call("write_file", Tier.CONFIRM, "write_file")
        ok = "WARNING" in text and "fetch_url" in text
        detail = "approved by typing write_file"
    except PermissionDenied as exc:
        ok = False
        detail = str(exc)
    _check("c", ok, detail)


def test_d() -> None:
    reset_session()
    mark_untrusted("fetch_url")
    denied = False
    deny_detail = ""
    try:
        _call("delete_file", Tier.ALWAYS_CONFIRM, "yes")
    except PermissionDenied as exc:
        denied = "typed confirmation was required" in str(exc).lower()
        deny_detail = str(exc)
    approved = False
    try:
        _call("delete_file", Tier.ALWAYS_CONFIRM, " delete_file ")
        approved = True
    except PermissionDenied as exc:
        deny_detail = str(exc)
    _check("d", denied and approved, f"yes_denied={denied}; spaced_name_approved={approved}; {deny_detail}")


def test_e() -> None:
    reset_session()
    mark_untrusted("fetch_url")
    try:
        text = _call("fetch_url", Tier.CONFIRM, "yes", "Fetch URL: https://example.test\nQuery: q")
        ok = (
            "WARNING: this session has read untrusted web content (fetch_url)." in text
            and "Allow? [yes/no]:" in text
        )
        detail = "banner printed, yes approved"
    except PermissionDenied as exc:
        ok = False
        detail = str(exc)
    _check("e", ok, detail)


def test_f() -> None:
    reset_session()
    mark_untrusted("fetch_url")

    def _boom(*_args, **_kwargs):
        raise AssertionError("input() was called")

    buf = io.StringIO()
    try:
        with patch("builtins.input", side_effect=_boom), redirect_stdout(buf):
            check_permission("read_file", Tier.AUTO_ALLOW, "read")
        text = buf.getvalue()
        ok = text == "" and "WARNING" not in text
        detail = "no prompt and no banner"
    except AssertionError as exc:
        ok = False
        detail = str(exc)
    _check("f", ok, detail)


def test_g() -> None:
    reset_session()
    mark_untrusted("fetch_url")
    reset_session()
    try:
        text = _call("write_file", Tier.CONFIRM, "yes")
        ok = (not is_tainted()) and "WARNING" not in text and "Allow? [yes/no]:" in text
        detail = "untainted yes approves"
    except PermissionDenied as exc:
        ok = False
        detail = str(exc)
    _check("g", ok, detail)


def _tool_call(call_id: str) -> dict:
    return {
        "id": call_id,
        "function": {
            "name": "fetch_url",
            "arguments": '{"url": "https://example.com", "query": "q"}',
        },
    }


def test_h() -> None:
    reset_session()
    saved = TOOL_FUNCTIONS["fetch_url"]

    def _ok(**_kwargs):
        return "fetched"

    def _bad(**_kwargs):
        raise ValueError("fetch failed")

    try:
        TOOL_FUNCTIONS["fetch_url"] = _ok
        execute_tool_calls([_tool_call("h1")])
        success_taints = is_tainted()
        reset_session()
        TOOL_FUNCTIONS["fetch_url"] = _bad
        execute_tool_calls([_tool_call("h2")])
        failure_clean = not is_tainted()
        ok = success_taints and failure_clean
        detail = f"success_taints={success_taints} failure_clean={failure_clean}"
    finally:
        TOOL_FUNCTIONS["fetch_url"] = saved
        reset_session()
    _check("h", ok, detail)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    test_a()
    test_b()
    test_c()
    test_d()
    test_e()
    test_f()
    test_g()
    test_h()
    reset_session()
    if FAILURES:
        print(f"\n{FAILURES} check(s) failed.")
        sys.exit(1)
    print("\nAll gate-taint checks passed.")


if __name__ == "__main__":
    main()
