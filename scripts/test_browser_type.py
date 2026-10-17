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


def test_7_submit_true_form() -> None:
    """Form field + submit=True: prompt shows dest; Enter fires; route logged."""
    session = _temp_session()
    reset_session()
    mark_untrusted("browser_open")
    captured: list[str] = []

    def _recording_gate(action, tier, description):
        captured.append(description)
        return check_permission(action, tier, description)

    try:
        page_submit_log: list[str] = []

        def _on_console(msg) -> None:
            if msg.text == "FORM_SUBMITTED":
                page_submit_log.append(msg.text)

        session.page.on("console", _on_console)
        session.page.set_content(
            """
            <html><body>
            <form id="f" action="https://other.example/search" method="get"
                  onsubmit="console.log('FORM_SUBMITTED'); return true;">
              <input type="text" name="q" placeholder="Query">
            </form>
            </body></html>
            """
        )
        browser_observe()
        meta = session.last_elements[1]
        assert meta.get("formAction") and "other.example/search" in str(
            meta["formAction"]
        )
        session.request_log.clear()
        page_submit_log.clear()
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_recording_gate,
        ), patch(
            "builtins.input", side_effect=lambda prompt="": "browser_type"
        ), redirect_stdout(io.StringIO()):
            browser_type(1, "ATP synthase", submit=True)
        prompt = captured[-1] if captured else ""
        route_hits = [
            (u, d)
            for (u, d) in session.request_log
            if "other.example" in u
        ]
        ok = (
            "After typing, Enter will be pressed. This submits the form to:"
            in prompt
            and "other.example" in prompt
            and "(method GET)" in prompt
            and "FORM_SUBMITTED" in page_submit_log
            and len(route_hits) >= 1
        )
        report(
            "7",
            ok,
            f"prompt={prompt!r} page_submit_log={page_submit_log!r} "
            f"route_hits={route_hits!r}",
        )
    finally:
        close_session()
        reset_session()


def test_8_submit_true_no_form() -> None:
    """Field outside a form + submit=True: not-in-form line; Enter reaches page."""
    session = _temp_session()
    reset_session()
    mark_untrusted("browser_open")
    captured: list[str] = []

    def _recording_gate(action, tier, description):
        captured.append(description)
        return check_permission(action, tier, description)

    try:
        session.page.set_content(
            """
            <html><body>
            <input id="t" type="text" placeholder="Loose">
            <script>
              window.__enterSeen = false;
              document.getElementById('t').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') window.__enterSeen = true;
              });
            </script>
            </body></html>
            """
        )
        browser_observe()
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_recording_gate,
        ), patch(
            "builtins.input", side_effect=lambda prompt="": "browser_type"
        ), redirect_stdout(io.StringIO()):
            browser_type(1, "hello", submit=True)
        prompt = captured[-1] if captured else ""
        enter_seen = session.page.evaluate("() => window.__enterSeen")
        ok = (
            "After typing, Enter will be pressed. This field is not in a form;"
            in prompt
            and "the page's own scripts decide what happens." in prompt
            and enter_seen is True
        )
        report("8", ok, f"prompt={prompt!r} enter_seen={enter_seen!r}")
    finally:
        close_session()
        reset_session()


def test_9_submit_false() -> None:
    """submit=False: no Enter line in prompt; form submit does not fire."""
    session = _temp_session()
    reset_session()
    captured: list[str] = []

    def _gate(action, tier, description):
        captured.append(description)
        return None

    try:
        session.page.set_content(
            """
            <html><body>
            <form action="https://other.example/search" method="get"
                  onsubmit="window.__formSubmitted = true; return false;">
              <input type="text" name="q" placeholder="Query">
            </form>
            <script>window.__formSubmitted = false;</script>
            </body></html>
            """
        )
        browser_observe()
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_gate,
        ):
            browser_type(1, "no-enter", submit=False)
        prompt = captured[-1] if captured else ""
        submitted = session.page.evaluate("() => window.__formSubmitted")
        value = session.page.evaluate(
            "() => document.querySelector('input').value"
        )
        ok = (
            "After typing, Enter will be pressed" not in prompt
            and submitted is False
            and value == "no-enter"
        )
        report(
            "9",
            ok,
            f"prompt={prompt!r} submitted={submitted!r} value={value!r}",
        )
    finally:
        close_session()
        reset_session()


def test_10_action_changed() -> None:
    """Form action changed after observe -> refused, nothing typed."""
    session = _temp_session()
    try:
        session.page.set_content(
            """
            <html><body>
            <form id="f" action="https://other.example/search" method="get">
              <input id="t" type="text" placeholder="Query">
            </form>
            </body></html>
            """
        )
        browser_observe()
        session.page.evaluate(
            "document.getElementById('f').action = "
            "'https://attacker.example/steal'"
        )
        raised = None
        try:
            with patch(
                "tools.browser.browser_tools.check_permission",
                return_value=None,
            ):
                browser_type(1, "should-not-appear", submit=True)
        except ValueError as exc:
            raised = str(exc)
        value = session.page.evaluate("() => document.getElementById('t').value")
        ok = (
            raised is not None
            and "page changed element [1]" in raised
            and value == ""
        )
        report("10", ok, f"error={raised!r} value={value!r}")
    finally:
        close_session()
        reset_session()


def test_11_enter_uses_default_button_formaction() -> None:
    """Textbox Enter destination prefers default submit button's formaction."""
    session = _temp_session()
    reset_session()
    mark_untrusted("browser_open")
    captured: list[str] = []

    def _recording_gate(action, tier, description):
        captured.append(description)
        return check_permission(action, tier, description)

    try:
        session.page.set_content(
            """
            <html><body>
            <form action="https://form.example/default" method="post">
              <input type="text" name="q" placeholder="Query">
              <button type="submit"
                formaction="https://other.example/x"
                formmethod="get">Go</button>
            </form>
            </body></html>
            """
        )
        browser_observe()
        meta = session.last_elements[1]
        with patch(
            "tools.browser.browser_tools.check_permission",
            side_effect=_recording_gate,
        ), patch(
            "builtins.input", side_effect=lambda prompt="": "browser_type"
        ), redirect_stdout(io.StringIO()):
            # Avoid real navigation: fill only (submit=False) after checking prompt
            # by calling with submit=True but stubbing type_text after gate.
            def _type_no_nav(ref, text, submit=False):
                # Verify element (formaction check) then fill without Enter.
                handle, _ = session._verify_element(ref)
                handle.fill(text)

            with patch.object(session, "type_text", side_effect=_type_no_nav):
                with patch.object(
                    session, "observe", lambda looking_for=None: "ok"
                ):
                    browser_type(1, "q", submit=True)
        prompt = captured[-1] if captured else ""
        ok = (
            "other.example/x" in str(meta.get("formAction"))
            and "other.example" in prompt
            and "(method GET)" in prompt
            and "form.example/default" not in prompt
        )
        report(
            "11",
            ok,
            f"meta_action={meta.get('formAction')!r} "
            f"meta_method={meta.get('formMethod')!r} prompt={prompt!r}",
        )
    finally:
        close_session()
        reset_session()


def test_12_dead_session_observe_message() -> None:
    """observe/click/type on a closed browser ask for browser_open."""
    session = _temp_session()
    try:
        session.page.set_content("<html><body><input></body></html>")
        browser_observe()
        session.page.close()
        raised = None
        try:
            browser_observe()
        except ValueError as exc:
            raised = str(exc)
        ok = raised == (
            "The browser closed unexpectedly. Call browser_open to start again."
        )
        report("12", ok, f"error={raised!r}")
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
        test_7_submit_true_form,
        test_8_submit_true_no_form,
        test_9_submit_false,
        test_10_action_changed,
        test_11_enter_uses_default_button_formaction,
        test_12_dead_session_observe_message,
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
