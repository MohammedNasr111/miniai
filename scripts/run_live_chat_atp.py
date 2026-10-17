"""Live two-turn chat: open/search Wikipedia, then quote the first sentence.

Pass = turn 2's answer contains the real first sentence of
https://en.wikipedia.org/wiki/ATP_synthase (fetched independently) AND
no quote-check note was appended.
"""

from __future__ import annotations

import re
import sys

import requests

from tests.support import answer_by_action

from scripts.agent_loop import QUOTE_CHECK_NOTE, _require_lemonade
from scripts.chat import end_session, new_session, run_user_turn
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session
from tools.browser.browser_tools import close_session
from tools.web.fetch_tools import extract_text

TURN1 = (
    "Open https://en.wikipedia.org in the browser and search for ATP "
    "synthase."
)
TURN2 = "What is the first sentence of that article? Quote it exactly."
ARTICLE_URL = "https://en.wikipedia.org/wiki/ATP_synthase"


def _real_first_sentence() -> str:
    """Fetch the article and return its first prose sentence (throwaway)."""
    headers = {"User-Agent": "MiniAI-live-check/1.0 (local test)"}
    # REST summary gives the lead paragraph without the infobox table.
    api = (
        "https://en.wikipedia.org/api/rest_v1/page/summary/ATP_synthase"
    )
    resp = requests.get(api, timeout=30, headers=headers)
    resp.raise_for_status()
    extract = (resp.json().get("extract") or "").strip()
    if not extract:
        # Fallback: HTML via trafilatura, skip table-like lines.
        page = requests.get(ARTICLE_URL, timeout=30, headers=headers)
        page.raise_for_status()
        _title, text = extract_text(
            page.text, page.headers.get("Content-Type", "text/html")
        )
        for line in text.splitlines():
            line = line.strip()
            if not line or "|" in line or line.startswith("---"):
                continue
            extract = line
            break
    if not extract:
        raise RuntimeError(f"Could not parse first sentence from {ARTICLE_URL}")
    m = re.match(r"(.+?\.)(\s|$)", extract, re.DOTALL)
    if not m:
        raise RuntimeError(f"No sentence boundary in extract: {extract!r}")
    return m.group(1).strip()


def _normalize(s: str) -> str:
    s = s.lower().replace("*", "").replace("_", "")
    return re.sub(r"\s+", " ", s).strip()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _require_lemonade()
    real = _real_first_sentence()
    print(f"REAL_FIRST_SENTENCE={real!r}")
    reset_session()
    close_session()
    provider = LemonadeProvider()
    session = new_session(provider)
    mapping = {
        "browser_open": "yes",
        "browser_type": "browser_type",
        "browser_click": "yes",
        "fetch_url": "yes",
    }
    a1 = ""
    a2 = ""
    try:
        try:
            with answer_by_action(mapping) as prompt_log:
                print(f"\n=== TURN 1 ===\nYou> {TURN1}")
                a1 = run_user_turn(session, TURN1)
                print(f"Assistant> {a1}")
                print(f"\n=== TURN 2 ===\nYou> {TURN2}")
                a2 = run_user_turn(session, TURN2)
                print(f"Assistant> {a2}")
            print("\n=== PROMPT LOG ===")
            for action, prompt, answer in prompt_log:
                print(f"Action={action!r} answer={answer!r}")
        except Exception as exc:
            print(f"LIVE_ERROR={type(exc).__name__}: {exc}")
        transcript_path = (
            str(session.transcript.path) if session.transcript else None
        )
        print(f"Transcript: {transcript_path}")
        print(f"TURN1_ANSWER={a1!r}")
        print(f"TURN2_ANSWER={a2!r}")
        has_sentence = bool(a2) and _normalize(real) in _normalize(a2)
        has_note = QUOTE_CHECK_NOTE.strip() in a2 or QUOTE_CHECK_NOTE in a2
        ok = has_sentence and not has_note
        print(f"has_real_sentence={has_sentence}")
        print(f"has_quote_check_note={has_note}")
        print(f"LIVE_OK={ok}")
        sys.exit(0 if ok else 1)
    finally:
        end_session(session)


if __name__ == "__main__":
    main()
