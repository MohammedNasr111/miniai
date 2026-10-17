"""Tainted sessions: data-carrying URLs need typed confirmation.

Offline; patches browser_open / fetch_url navigation so no network is needed
after the gate.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

from security.gate import PermissionDenied, Tier, check_permission, mark_untrusted, reset_session
from tools.browser import browser_tools
from tools.browser.browser_tools import browser_open, close_session
from tools.web.fetch_tools import fetch_url

FAILURES: list[str] = []

QUERY_URL = "https://en.wikipedia.org/w/index.php?search=ATP"
PLAIN_URL = "https://en.wikipedia.org/wiki/ATP_synthase"


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _drive(action: str, url: str, description: str, answers: list[str]):
    """Call check_permission with url=; return (raised_or_None, stdout)."""
    it = iter(answers)
    buf = io.StringIO()

    def _input(prompt=""):
        print(prompt, end="")
        return next(it)

    raised = None
    with patch("builtins.input", side_effect=_input), redirect_stdout(buf):
        try:
            check_permission(
                action=action,
                tier=Tier.CONFIRM,
                description=description,
                url=url,
            )
        except PermissionDenied as exc:
            raised = exc
        except StopIteration as exc:
            raised = exc
    return raised, buf.getvalue()


def test_browser_open_cases() -> None:
    # (1) tainted + query -> yes denied, browser_open approves
    reset_session()
    mark_untrusted("browser_open")
    raised, out = _drive(
        "browser_open",
        QUERY_URL,
        f"Open in browser:\n{QUERY_URL}",
        ["yes"],
    )
    yes_denied = isinstance(raised, PermissionDenied) and "Typed confirmation" in str(
        raised
    )
    has_line = (
        "This URL carries data (shown above). Typed confirmation required." in out
    )
    raised2, out2 = _drive(
        "browser_open",
        QUERY_URL,
        f"Open in browser:\n{QUERY_URL}",
        ["browser_open"],
    )
    name_ok = raised2 is None
    report(
        "1",
        yes_denied and has_line and name_ok,
        f"yes_denied={yes_denied} has_line={has_line} name_ok={name_ok}",
    )

    # (2) tainted + plain wiki URL -> yes approves
    reset_session()
    mark_untrusted("browser_open")
    raised, out = _drive(
        "browser_open",
        PLAIN_URL,
        f"Open in browser:\n{PLAIN_URL}",
        ["yes"],
    )
    yes_ok = raised is None and "Allow? [yes/no]:" in out
    no_typed = "Type browser_open" not in out
    report("2", yes_ok and no_typed, f"yes_ok={yes_ok} no_typed={no_typed} out={out!r}")

    # (3) untainted + query -> yes approves
    reset_session()
    raised, out = _drive(
        "browser_open",
        QUERY_URL,
        f"Open in browser:\n{QUERY_URL}",
        ["yes"],
    )
    untainted_ok = raised is None and "Allow? [yes/no]:" in out
    report("3", untainted_ok, f"untainted_ok={untainted_ok}")


def test_fetch_url_cases() -> None:
    # (4) same three for fetch_url
    results = []

    reset_session()
    mark_untrusted("fetch_url")
    raised, out = _drive(
        "fetch_url",
        QUERY_URL,
        f"Fetch URL:\n{QUERY_URL}\nQuery: q",
        ["yes"],
    )
    yes_denied = isinstance(raised, PermissionDenied)
    has_line = "This URL carries data (shown above). Typed confirmation required." in out
    raised2, _ = _drive(
        "fetch_url",
        QUERY_URL,
        f"Fetch URL:\n{QUERY_URL}\nQuery: q",
        ["fetch_url"],
    )
    results.append(("4a", yes_denied and has_line and raised2 is None))

    reset_session()
    mark_untrusted("fetch_url")
    raised, out = _drive(
        "fetch_url",
        PLAIN_URL,
        f"Fetch URL:\n{PLAIN_URL}\nQuery: q",
        ["yes"],
    )
    results.append(("4b", raised is None and "Allow? [yes/no]:" in out))

    reset_session()
    raised, out = _drive(
        "fetch_url",
        QUERY_URL,
        f"Fetch URL:\n{QUERY_URL}\nQuery: q",
        ["yes"],
    )
    results.append(("4c", raised is None and "Allow? [yes/no]:" in out))

    ok = all(r[1] for r in results)
    report("4", ok, f"results={results!r}")


def test_browser_open_passes_url_kwarg() -> None:
    """browser_open forwards url= into the gate (smoke via mock)."""
    reset_session()
    mark_untrusted("x")
    seen = {}

    def _gate(action, tier, description, url=None):
        seen["url"] = url
        seen["action"] = action
        raise PermissionDenied("stop")

    close_session()
    try:
        with patch("tools.browser.browser_tools.check_permission", side_effect=_gate):
            with patch("tools.browser.browser_tools.validate_url", lambda u: None):
                try:
                    browser_open(QUERY_URL)
                except PermissionDenied:
                    pass
        report(
            "browser_open_url_kwarg",
            seen.get("url") == QUERY_URL and seen.get("action") == "browser_open",
            f"seen={seen!r}",
        )
    finally:
        close_session()
        reset_session()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for test in (
        test_browser_open_cases,
        test_fetch_url_cases,
        test_browser_open_passes_url_kwarg,
    ):
        try:
            test()
        except Exception as exc:
            report(test.__name__, False, f"{type(exc).__name__}: {exc}")
        finally:
            reset_session()
            close_session()
    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
