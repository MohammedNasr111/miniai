"""Stage 7b offline checks for browser_type, describe_url, form submit, atomic capture.

Uses temp browser profiles. Does not touch real memory/vector stores.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
from contextlib import redirect_stdout
from unittest.mock import patch

os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

from security.gate import (
    PermissionDenied,
    Tier,
    check_permission,
    mark_untrusted,
    reset_session,
)
from tools.browser import browser_tools
from tools.browser.browser_tools import (
    browser_click,
    browser_observe,
    browser_type,
    close_session,
)
from tools.browser.session import BrowserSession
from tools.web.url_display import describe_url

FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _temp_session() -> BrowserSession:
    close_session()
    tmp = tempfile.mkdtemp()
    session = BrowserSession(headless=False, profile_dir=tmp)
    browser_tools._session = session
    return session


def test_1_refusals() -> None:
    session = _temp_session()
    try:
        session.page.set_content(
            """
            <html><body>
            <input id="pw" type="password" placeholder="Password">
            <input id="cc" type="text" autocomplete="cc-number" placeholder="Card">
            <input id="card" type="text" name="card_no" placeholder="Card no">
            </body></html>
            """
        )
        browser_observe()
        cases = []
        for ref, label in ((1, "password"), (2, "cc-number"), (3, "card_no")):
            gate_calls: list = []

            def _gate(*args, **kwargs):
                gate_calls.append((args, kwargs))
                raise AssertionError("gate should not be reached")

            raised = None
            try:
                with patch(
                    "tools.browser.browser_tools.check_permission",
                    side_effect=_gate,
                ):
                    browser_type(ref, "secret-value")
            except ValueError as exc:
                raised = str(exc)
            value = session.page.evaluate(
                f"() => document.querySelectorAll('input')[{ref - 1}].value"
            )
            ok = (
                raised is not None
                and "passwords or payment details" in raised
                and gate_calls == []
                and value == ""
            )
            cases.append((label, ok, raised, value, len(gate_calls)))
        all_ok = all(c[1] for c in cases)
        report("1", all_ok, f"cases={cases!r}")
    finally:
        close_session()
        reset_session()


def test_2_tainted_type() -> None:
    session = _temp_session()
    reset_session()
    mark_untrusted("browser_open")
    text = "Hello typed text"
    captured: list[str] = []

    def _recording_gate(action, tier, description):
        captured.append(description)
        return check_permission(action, tier, description)

    try:
        session.page.set_content(
            '<html><body><input type="text" placeholder="Search box"></body></html>'
        )
        browser_observe()

        yes_denied = False
        buf = io.StringIO()
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_recording_gate,
        ), patch("builtins.input", side_effect=lambda prompt="": "yes"), redirect_stdout(
            buf
        ):
            try:
                browser_type(1, text)
            except PermissionDenied:
                yes_denied = True

        value_after_yes = session.page.evaluate(
            "() => document.querySelector('input').value"
        )

        captured.clear()
        typed_ok = False
        buf2 = io.StringIO()
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_recording_gate,
        ), patch(
            "builtins.input", side_effect=lambda prompt="": "browser_type"
        ), redirect_stdout(buf2):
            browser_type(1, text)
            typed_ok = True

        prompt = captured[-1] if captured else ""
        value = session.page.evaluate("() => document.querySelector('input').value")
        has_origin = "Type into page:" in prompt
        has_label = (
            'Field [1] textbox, label supplied by the page: "Search box"' in prompt
        )
        has_text = f"Text to type ({len(text)} characters):\n{text}" in prompt
        has_warn = (
            "WARNING: this site can read the text as soon as it is typed, even if"
            in prompt
        )
        ok = (
            yes_denied
            and value_after_yes == ""
            and typed_ok
            and has_origin
            and has_label
            and has_text
            and has_warn
            and value == text
        )
        report(
            "2",
            ok,
            f"yes_denied={yes_denied} value_after_yes={value_after_yes!r} "
            f"typed_ok={typed_ok} value={value!r} origin={has_origin} "
            f"label={has_label} text={has_text} warn={has_warn} prompt={prompt!r}",
        )
    finally:
        close_session()
        reset_session()


def test_3_label_change() -> None:
    session = _temp_session()
    try:
        session.page.set_content(
            '<html><body><input id="t" type="text" placeholder="Original"></body></html>'
        )
        browser_observe()
        session.page.evaluate(
            "document.getElementById('t').setAttribute('placeholder', 'Changed')"
        )
        raised = None
        try:
            with patch(
                "tools.browser.browser_tools.check_permission",
                return_value=None,
            ):
                browser_type(1, "should-not-appear")
        except ValueError as exc:
            raised = str(exc)
        value = session.page.evaluate("() => document.getElementById('t').value")
        ok = (
            raised is not None
            and "page changed element [1]" in raised
            and value == ""
        )
        report("3", ok, f"error={raised!r} value={value!r}")
    finally:
        close_session()
        reset_session()


def test_4_describe_url() -> None:
    url = (
        "https://attacker.example/collect/James%20Smith?d="
        "Battery%20at%20100%25&x=1#a%20b"
    )
    shown = describe_url(url)
    ok = (
        shown.splitlines()[0] == url
        and "Data carried in this URL:" in shown
        and "path: /collect/James Smith" in shown
        and "d = Battery at 100%" in shown
        and "x = 1" in shown
        and "fragment: a b" in shown
    )
    report("4", ok, f"shown=\n{shown}")


def test_5_submit_form_prompt() -> None:
    session = _temp_session()
    captured: list[str] = []

    def _gate(action, tier, description):
        captured.append(description)
        return None

    try:
        session.page.set_content(
            """
            <html><body>
            <form action="https://other.example/collect" method="post">
              <button type="submit">Send</button>
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
            and "https://other.example/collect" in prompt
            and "(method POST)" in prompt
        )
        report("5", ok, f"prompt={prompt!r}")
    finally:
        close_session()
        reset_session()


def test_6_atomic_16_17_and_timing() -> None:
    import scripts.test_browser_session as tbs

    session = _temp_session()
    try:
        saved = list(tbs.FAILURES)
        tbs.FAILURES.clear()
        tbs.check_16(session)
        tbs.check_17(session)
        ok_16_17 = tbs.FAILURES == []
        detail = f"session_failures={list(tbs.FAILURES)}"
        tbs.FAILURES[:] = saved

        wiki_ms = None
        wiki_err = None
        try:
            session.open("https://en.wikipedia.org/wiki/Mitochondrion")
            t0 = time.perf_counter()
            session.observe()
            wiki_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as exc:
            wiki_err = f"{type(exc).__name__}: {exc}"
        report(
            "6",
            ok_16_17 and wiki_ms is not None,
            f"{detail}; observe_wikipedia_ms_after={wiki_ms!r} "
            f"observe_wikipedia_ms_before=N/A (already atomic in tree); "
            f"err={wiki_err!r}",
        )
    finally:
        close_session()
        reset_session()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for test in (
        test_1_refusals,
        test_2_tainted_type,
        test_3_label_change,
        test_4_describe_url,
        test_5_submit_form_prompt,
        test_6_atomic_16_17_and_timing,
    ):
        try:
            test()
        except Exception as exc:
            report(test.__name__, False, f"{type(exc).__name__}: {exc}")
        finally:
            close_session()
            reset_session()
    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
