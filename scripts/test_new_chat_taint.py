"""Offline: New chat resets session taint."""

from __future__ import annotations

from tests.support import use_temp_data

use_temp_data()

from security.gate import is_tainted, mark_untrusted, reset_session
from app.webview_approver import AppBridge

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    reset_session()
    bridge = AppBridge()
    mark_untrusted("fetch_url")
    _check("tainted_before", is_tainted(), "")
    res = bridge.new_chat()
    _check("is_tainted_false", is_tainted() is False, f"tainted={is_tainted()}")
    _check(
        "payload_untainted",
        isinstance(res, dict) and res.get("tainted") is False,
        repr(res),
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
