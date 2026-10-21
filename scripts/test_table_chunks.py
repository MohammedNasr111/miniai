"""Offline tests for Stage 12b-pre2 table-aware chunking + newest-first order."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0
TODAY = date(2026, 10, 21)


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def test_header_on_every_table_chunk() -> None:
    from tools.filesystem.chunking import chunk_text

    header = "| Branch | Schedule | Status | First release |"
    sep = "|---|---|---|---|"
    rows = [
        f"| 3.{i} | PEP {700+i} | bugfix | 202{i}-10-0{(i%9)+1} |"
        for i in range(10, 40)
    ]
    text = "\n".join([header, sep] + rows)
    chunks = chunk_text(text, chunk_size=180, overlap=20)
    ok = len(chunks) >= 2 and all(
        "(table header repeated)" in c and header in c and sep in c for c in chunks
    )
    # Data rows preserved across chunks
    joined = "\n".join(chunks)
    rows_ok = all(r in joined for r in rows)
    _check(
        "header_on_every_chunk",
        ok and rows_ok,
        f"n_chunks={len(chunks)} rows_ok={rows_ok}",
    )


def test_non_table_unchanged() -> None:
    from tools.filesystem.chunking import chunk_text

    text = "Mitochondria produce ATP. " * 40
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    ok = all("(table header repeated)" not in c and "|" not in c for c in chunks)
    _check("non_table_unchanged", ok and len(chunks) >= 2, f"n={len(chunks)}")


def test_no_double_header() -> None:
    from tools.filesystem.chunking import chunk_text

    header = "| A | B |"
    sep = "|---|---|"
    rows = ["| 1 | 2 |", "| 3 | 4 |"]
    text = "\n".join([header, sep] + rows)
    # Large budget so one chunk contains everything including natural header.
    chunks = chunk_text(text, chunk_size=5000, overlap=10)
    ok = len(chunks) == 1 and chunks[0].count(header) == 1
    # With our packer, single chunk still uses the repeated prefix once.
    # Accept exactly one header occurrence in the chunk body after prefix.
    body = chunks[0]
    count = body.count(header)
    ok = len(chunks) == 1 and count == 1
    _check("no_double_header", ok, f"count={count} chunk0={body!r}")


def test_newest_first_ordering() -> None:
    from tools.web.recency import (
        is_older_than_6_months,
        order_pages_newest_first,
        source_date_header_line,
    )

    pages = [
        SimpleNamespace(rank=1, page_date=date(2025, 10, 7), final_url="https://old.example/"),
        SimpleNamespace(rank=2, page_date=None, final_url="https://unk.example/"),
        SimpleNamespace(
            rank=3, page_date=date(2026, 10, 9), final_url="https://new.example/"
        ),
        SimpleNamespace(
            rank=4, page_date=date(2026, 9, 1), final_url="https://mid.example/"
        ),
    ]
    ordered = order_pages_newest_first(pages, today=TODAY)
    domains = [p.final_url for p in ordered]
    # recent newest-first, then unknown, then older
    ok = domains == [
        "https://new.example/",
        "https://mid.example/",
        "https://unk.example/",
        "https://old.example/",
    ] and [p.rank for p in ordered] == [1, 2, 3, 4]
    old_line = source_date_header_line(
        4, "https://old.example/", date(2025, 10, 7), today=TODAY
    )
    ok2 = "(older than 6 months)" in old_line and is_older_than_6_months(
        date(2025, 10, 7), today=TODAY
    )
    _check("newest_first_ordering", ok and ok2, f"order={domains} old_line={old_line!r}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_header_on_every_table_chunk()
    test_non_table_unchanged()
    test_no_double_header()
    test_newest_first_ordering()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
