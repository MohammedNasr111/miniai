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
from security.provenance import remember_url, remember_urls_from_text
from tools.browser import browser_tools
from tools.browser.browser_tools import browser_click, browser_observe, close_session
from tools.browser.session import BrowserSession
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
