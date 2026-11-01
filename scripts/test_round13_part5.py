"""Round 13 Part 5 — eval fetch allow-list; product loopback still blocked."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from eval.eval_fetch_allowlist import (
        allow_eval_fetch_host_port,
        clear_eval_fetch_allowlist,
        is_eval_fetch_allowed,
        revoke_eval_fetch_host_port,
    )
    from eval.eval_lock import acquire_eval_lock, release_eval_lock
    from tools.web.fetch_tools import validate_url

    clear_eval_fetch_allowlist()
    release_eval_lock()

    # Outside evals: loopback still blocked (product behaviour unchanged).
    blocked_ok = False
    try:
        validate_url("http://127.0.0.1:34567/page.html")
    except ValueError as exc:
        blocked_ok = "blocked address" in str(exc).lower() or "loopback" in str(exc).lower()
        detail = str(exc)
    else:
        detail = "accepted without lock"
    _check("outside_eval_loopback_blocked", blocked_ok, detail)

    # With lock + exact allow: that host:port is permitted.
    acquire_eval_lock()
    try:
        allow_eval_fetch_host_port("127.0.0.1", 34567)
        _check(
            "allowlist_permits_exact",
            is_eval_fetch_allowed("http://127.0.0.1:34567/page.html"),
        )
        allowed_ok = False
        try:
            validate_url("http://127.0.0.1:34567/page.html")
            allowed_ok = True
            detail2 = "allowed"
        except ValueError as exc:
            detail2 = str(exc)
        _check("with_lock_allowed_host_port", allowed_ok, detail2)

        # Different port still blocked even with lock.
        other_blocked = False
        try:
            validate_url("http://127.0.0.1:34568/page.html")
        except ValueError:
            other_blocked = True
        _check("other_port_still_blocked", other_blocked)

        revoke_eval_fetch_host_port("127.0.0.1", 34567)
        after_revoke = False
        try:
            validate_url("http://127.0.0.1:34567/page.html")
        except ValueError:
            after_revoke = True
        _check("revoked_again_blocked", after_revoke)
    finally:
        clear_eval_fetch_allowlist()
        release_eval_lock()

    # After releasing lock, allowlist entries alone must not open loopback.
    allow_eval_fetch_host_port("127.0.0.1", 34567)
    no_lock = False
    try:
        validate_url("http://127.0.0.1:34567/page.html")
    except ValueError:
        no_lock = True
    _check("allowlist_ignored_without_lock", no_lock)
    clear_eval_fetch_allowlist()

    # Redirected LOCALAPPDATA must not hide a real eval.lock (Part 3 + 5).
    import os
    import tempfile
    from eval.eval_lock import eval_lock_path

    acquire_eval_lock()
    try:
        real_lock = eval_lock_path()
        _check("lock_under_real_localappdata", real_lock.is_file(), str(real_lock))
        with tempfile.TemporaryDirectory(prefix="miniai_redir_") as td:
            old = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = td
            try:
                allow_eval_fetch_host_port("127.0.0.1", 34567)
                ok_redir = False
                try:
                    validate_url("http://127.0.0.1:34567/page.html")
                    ok_redir = True
                except ValueError as exc:
                    detail_r = str(exc)
                else:
                    detail_r = "allowed under redirected LOCALAPPDATA"
                _check("lock_visible_under_redirect", ok_redir, detail_r)
            finally:
                if old is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old
                clear_eval_fetch_allowlist()
    finally:
        release_eval_lock()
        clear_eval_fetch_allowlist()

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
