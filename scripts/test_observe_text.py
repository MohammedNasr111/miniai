"""Offline checks for observe() page-text layout (trafilatura + sections)."""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

from tools.browser.browser_tools import close_session
from tools.browser.session import BrowserSession, looking_for_words
from security.gate import reset_session

FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _temp_session() -> BrowserSession:
    close_session()
    return BrowserSession(headless=True, profile_dir=tempfile.mkdtemp())


def _start_section(observed: str) -> tuple[str, str]:
    """Return (header, body) for the start section."""
    lines = observed.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Page text - start"):
            body = lines[i + 1] if i + 1 < len(lines) else ""
            return line, body
    return "", ""


def _around_sections(observed: str) -> list[tuple[str, str]]:
    out = []
    lines = observed.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Page text - around"):
            body = lines[i + 1] if i + 1 < len(lines) else ""
            out.append((line, body))
    return out


def test_1_table_then_paragraph() -> None:
    session = _temp_session()
    try:
        lead = (
            "ATP synthase is an enzyme that catalyzes the formation of the "
            "energy storage molecule adenosine triphosphate."
        )
        session.page.set_content(
            f"""
            <html><body>
            <table>
              <tr><td>{"noise cell data " * 40}</td></tr>
              <tr><td>{"more table noise " * 40}</td></tr>
            </table>
            <article>
              <p>{lead} Later paragraphs discuss other topics.</p>
            </article>
            </body></html>
            """
        )
        observed = session.observe()
        header, body = _start_section(observed)
        ok = (
            "from article text" in header
            and lead[:40] in body
            and body.find(lead[:40]) < 200
        )
        report("1", ok, f"header={header!r} body_start={body[:120]!r}")
    finally:
        session.close()
        reset_session()


def test_2_stop_words_only() -> None:
    session = _temp_session()
    try:
        assert looking_for_words("first sentence") == []
        session.page.set_content(
            """
            <html><body>
            <article><p>Hello world. Another sentence about enzymes.</p></article>
            </body></html>
            """
        )
        observed = session.observe(looking_for="first sentence")
        header, body = _start_section(observed)
        around = _around_sections(observed)
        ok = (
            header.startswith("Page text - start")
            and "up to 3000 characters" in header
            and body != ""
            and around == []
        )
        report(
            "2",
            ok,
            f"header={header!r} around={around!r} body={body[:80]!r}",
        )
    finally:
        session.close()
        reset_session()


def test_3_match_beyond_1500() -> None:
    session = _temp_session()
    try:
        # Ensure membrane sits after 1500 with a clear sentence start nearby.
        filler = "x" * 1600
        mid = (
            "Earlier clauses do not matter. "
            "The membrane is where protons cross the inner layer."
        )
        html_body = f"<html><body><article><p>{filler}{mid}</p></article></body></html>"
        # Prefer a controlled full_text path: patch extract_text to return our text.
        crafted = filler + mid
        assert crafted.lower().find("membrane") > 1500

        session.page.set_content(html_body)
        with patch(
            "tools.browser.session.extract_text",
            return_value=(None, crafted),
        ):
            observed = session.observe(looking_for="membrane")
        header, start_body = _start_section(observed)
        around = _around_sections(observed)
        ok_around = len(around) == 1
        around_header, around_body = around[0] if around else ("", "")
        # Second section starts at the sentence beginning.
        ok = (
            "up to 1500 characters" in header
            and ok_around
            and "around 'membrane'" in around_header
            and around_body.startswith("The membrane is where protons")
            and "membrane" in around_body.lower()
        )
        report(
            "3",
            ok,
            f"header={header!r} around_header={around_header!r} "
            f"around_body={around_body[:80]!r} start_len={len(start_body)}",
        )
    finally:
        session.close()
        reset_session()


def test_4_trafilatura_fallback() -> None:
    session = _temp_session()
    try:
        session.page.set_content(
            """
            <html><body>
            <main>
              <p>Fallback paragraph about mitochondria producing ATP.</p>
            </main>
            </body></html>
            """
        )
        with patch(
            "tools.browser.session.extract_text",
            side_effect=ValueError("No readable text extracted"),
        ):
            observed = session.observe()
        header, body = _start_section(observed)
        ok = (
            "from main content" in header
            and "Fallback paragraph" in body
            and "from article text" not in header
        )
        report("4", ok, f"header={header!r} body={body[:100]!r}")
    finally:
        session.close()
        reset_session()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for test in (
        test_1_table_then_paragraph,
        test_2_stop_words_only,
        test_3_match_beyond_1500,
        test_4_trafilatura_fallback,
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
