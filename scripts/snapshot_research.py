"""Fetch live pages for the retrieval eval. Run once.

Saves one JSON file per question under tests/fixtures/web_snapshots/.
That folder is gitignored. Does not rank or embed.
"""

import json
import sys
import time
from pathlib import Path

from tools.web.fetch_tools import download, extract_text, validate_url
from tools.web.research_tools import (
    RESEARCH_DEADLINE_SECONDS,
    SEARCH_COUNT,
    _safe,
    _short_reason,
)
from tools.web.search.tavily import TavilyProvider

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "web_snapshots"
MAX_PAGES = 4

QUESTIONS = [
    ("What is the latest stable version of Python?", "3.15"),
    ("What molecule do mitochondria produce?", "ATP"),
    ("What is the default port of Lemonade Server?", "13305"),
    ("What is the boiling point of water at sea level in Fahrenheit?", "212"),
    ("Who wrote the novel Nineteen Eighty-Four?", "Orwell"),
    ("What is the capital of Australia?", "Canberra"),
    ("In what year did Python 2 reach end of life?", "2020"),
    ("What year was the first iPhone released?", "2007"),
]


def _collect(question: str) -> tuple[list[dict], list[str]]:
    started = time.monotonic()
    results = TavilyProvider().search(question, SEARCH_COUNT)
    pages: list[dict] = []
    skipped: list[str] = []
    for result in results:
        if len(pages) >= MAX_PAGES:
            break
        if time.monotonic() - started >= RESEARCH_DEADLINE_SECONDS:
            skipped.append("skipped: remaining results (time budget reached)")
            break
        try:
            validate_url(result.url)
            final_url, content_type, body = download(result.url)
            title, extracted = extract_text(body, content_type)
        except ValueError as exc:
            skipped.append(f"skipped: {_safe(result.url)} ({_short_reason(exc)})")
            continue
        pages.append(
            {
                "rank": len(pages) + 1,
                "url": final_url,
                "title": title,
                "text": extracted,
            }
        )
    return pages, skipped


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    for number, (question, expected) in enumerate(QUESTIONS, start=1):
        print(f"SNAPSHOT {number}: {question}")
        pages, skipped = _collect(question)
        payload = {
            "question": question,
            "expected": expected,
            "pages": pages,
            "skipped": skipped,
        }
        path = OUT / f"{number:02d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        urls = [page["url"] for page in pages]
        print(f"  pages={len(pages)} skipped={len(skipped)}")
        for url in urls:
            print(f"  fetched {url}")
        for line in skipped:
            print(f"  {line}")
    print(f"Wrote {len(QUESTIONS)} snapshots to {OUT}")


if __name__ == "__main__":
    main()
