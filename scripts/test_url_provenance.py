"""Offline checks for URL provenance gate and related 7b fixes."""

from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from unittest.mock import patch

os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

from security.gate import PermissionDenied, Tier, check_permission, mark_untrusted, reset_session
from security.provenance import (
    is_known_url,
    normalize_url,
    remember_url,
    remember_urls_from_text,
)
from tools.browser import browser_tools
from tools.browser.browser_tools import (
    browser_click,
    browser_observe,
    browser_open,
    close_session,
)
from tools.browser.session import BrowserSession
from tools.web.fetch_tools import validate_url
from tools.web.url_display import describe_url

FAILURES: list[str] = []

USER_URL = "https://en.wikipedia.org/wiki/ATP_synthase"
HREF_URL = "https://en.wikipedia.org/wiki/Adenosine_triphosphate"
ATTACKER_PATH = "https://attacker.example/collect/James-teaches"
ATTACKER_HOST = "https://james-teaches.attacker.example/"
WIKI_SEARCH = "https://en.wikipedia.org/w/index.php?search=ATP+synthase"
ANY_URL = "https://example.com/anything?x=1"


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _drive(action: str, url: str, description: str, answers: list[str]):
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


def _temp_session() -> BrowserSession:
    close_session()
    tmp = tempfile.mkdtemp()
    session = BrowserSession(headless=False, profile_dir=tmp)
    browser_tools._session = session
    return session


def test_1_user_message_url() -> None:
    reset_session()
    remember_urls_from_text(f"Please open {USER_URL} for me.")
    mark_untrusted("browser_open")
    raised, out = _drive(
        "browser_open",
        USER_URL,
        f"Open in browser:\n{USER_URL}",
        ["yes"],
    )
    ok = raised is None and "Allow? [yes/no]:" in out and "model constructed" not in out
    report("1", ok, f"raised={raised!r} out_tail={out[-200:]!r}")


def test_2_observation_href() -> None:
    reset_session()
    mark_untrusted("browser_observe")
    remember_url(HREF_URL)
    raised, out = _drive(
        "browser_open",
        HREF_URL,
        f"Open in browser:\n{HREF_URL}",
        ["yes"],
    )
    ok = raised is None and "Allow? [yes/no]:" in out
    report("2", ok, f"raised={raised!r}")


def test_3_model_constructed_attacker() -> None:
    reset_session()
    mark_untrusted("browser_open")
    results = []
    for url in (ATTACKER_PATH, ATTACKER_HOST):
        raised, out = _drive(
            "browser_open",
            url,
            f"Open in browser:\n{url}",
            ["yes"],
        )
        yes_denied = isinstance(raised, PermissionDenied)
        has_line = "model constructed it" in out
        raised2, _ = _drive(
            "browser_open",
            url,
            f"Open in browser:\n{url}",
            ["browser_open"],
        )
        results.append((url, yes_denied and has_line and raised2 is None))
    ok = all(r[1] for r in results)
    report("3", ok, f"results={results!r}")


def test_4_model_constructed_wiki_search() -> None:
    reset_session()
    mark_untrusted("browser_open")
    raised, out = _drive(
        "browser_open",
        WIKI_SEARCH,
        f"Open in browser:\n{WIKI_SEARCH}",
        ["yes"],
    )
    ok = (
        isinstance(raised, PermissionDenied)
        and "model constructed it" in out
        and "Type browser_open to approve" in out
    )
    report("4", ok, f"raised={raised!r} has_line={'model constructed' in out}")


def test_5_untainted_any() -> None:
    reset_session()
    raised, out = _drive(
        "browser_open",
        ANY_URL,
        f"Open in browser:\n{ANY_URL}",
        ["yes"],
    )
    ok = raised is None and "Allow? [yes/no]:" in out
    report("5", ok, f"raised={raised!r}")


def test_6_describe_url_single_decode() -> None:
    shown = describe_url("https://example.com/?d=100%2541")
    ok = "d = 100%41" in shown and "100A" not in shown
    report("6", ok, f"shown=\n{shown}")


def test_7_formaction() -> None:
    session = _temp_session()
    captured: list[str] = []

    def _gate(action, tier, description, url=None):
        captured.append(description)
        return None

    try:
        session.page.set_content(
            """
            <html><body>
            <form action="https://form.example/elsewhere" method="post">
              <button type="submit"
                formaction="https://other.example/x"
                formmethod="get">Send</button>
            </form>
            </body></html>
            """
        )
        browser_observe()
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_gate,
        ):
            with patch.object(session, "click", lambda ref: None):
                with patch.object(
                    session, "observe", lambda looking_for=None: "ok"
                ):
                    browser_click(1)
        prompt = captured[0] if captured else ""
        ok = (
            "Submits a form to:" in prompt
            and "https://other.example/x" in prompt
            and "form.example/elsewhere" not in prompt
        )
        report("7", ok, f"prompt={prompt!r}")
    finally:
        close_session()
        reset_session()


def test_8_semicolon_path_not_known() -> None:
    """Path with ;... is distinct from the bare path in the known set."""
    reset_session()
    known = "https://known.example/page"
    variant = "https://known.example/page;James-data"
    remember_url(known)
    assert is_known_url(known)
    assert not is_known_url(variant)
    assert normalize_url(variant) == "https://known.example/page;James-data"
    mark_untrusted("browser_open")
    raised, out = _drive(
        "browser_open",
        variant,
        f"Open in browser:\n{variant}",
        ["yes"],
    )
    ok = (
        isinstance(raised, PermissionDenied)
        and "model constructed it" in out
        and "Type browser_open to approve" in out
    )
    report("8", ok, f"raised={raised!r} known={is_known_url(known)}")


def test_9_credentials_refused_before_prompt() -> None:
    reset_session()
    mark_untrusted("browser_open")
    gate_calls: list = []

    def _gate(*args, **kwargs):
        gate_calls.append((args, kwargs))
        raise AssertionError("gate should not be reached")

    raised = None
    try:
        with patch("tools.browser.browser_tools.check_permission", side_effect=_gate):
            with patch("tools.browser.browser_tools.validate_url", wraps=validate_url):
                # Real validate_url must run (credentials). Do not mock it away.
                browser_open("https://data@known.example/page")
    except ValueError as exc:
        raised = str(exc)
    ok = (
        raised is not None
        and "embedded credentials" in raised
        and gate_calls == []
    )
    # Also confirm validate_url alone.
    validate_raised = None
    try:
        validate_url("https://data@known.example/page")
    except ValueError as exc:
        validate_raised = str(exc)
    ok = ok and validate_raised is not None and "embedded credentials" in validate_raised
    report(
        "9",
        ok,
        f"raised={raised!r} validate={validate_raised!r} gate={len(gate_calls)}",
    )


def test_10_routed_credentials_blocked() -> None:
    session = _temp_session()
    try:
        # Pretend the host was already allowed so only the credential check matters.
        session._host_decisions["example.com"] = None
        reason = session._decide("https://user:pass@example.com/secret")
        decide_ok = reason is not None and "embedded credentials" in reason
        # Navigate directly (bypassing session.open) so the route handler runs.
        before = len(session.blocked)
        try:
            session.page.goto(
                "https://user:pass@example.com/x",
                timeout=5_000,
                wait_until="commit",
            )
        except Exception:
            pass
        session.page.wait_for_timeout(300)
        routed_ok = any(
            "embedded credentials" in (b.get("reason") or "")
            for b in session.blocked[before:]
        )
        report(
            "10",
            decide_ok and routed_ok,
            f"decide={reason!r} blocked={session.blocked[before:]!r} "
            f"routed_ok={routed_ok}",
        )
    finally:
        close_session()
        reset_session()


def test_11_textbox_click_refused() -> None:
    session = _temp_session()
    gate_calls: list = []

    def _gate(*args, **kwargs):
        gate_calls.append((args, kwargs))
        raise AssertionError("gate should not be reached")

    try:
        session.page.set_content(
            '<html><body><input type="text" placeholder="Search"></body></html>'
        )
        browser_observe()
        raised = None
        try:
            with patch(
                "tools.browser.browser_tools.check_permission",
                side_effect=_gate,
            ):
                browser_click(1)
        except ValueError as exc:
            raised = str(exc)
        ok = (
            raised is not None
            and "text field" in raised
            and "browser_type" in raised
            and gate_calls == []
        )
        report("11", ok, f"raised={raised!r} gate={len(gate_calls)}")
    finally:
        close_session()
        reset_session()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for test in (
        test_1_user_message_url,
        test_2_observation_href,
        test_3_model_constructed_attacker,
        test_4_model_constructed_wiki_search,
        test_5_untainted_any,
        test_6_describe_url_single_decode,
        test_7_formaction,
        test_8_semicolon_path_not_known,
        test_9_credentials_refused_before_prompt,
        test_10_routed_credentials_blocked,
        test_11_textbox_click_refused,
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
