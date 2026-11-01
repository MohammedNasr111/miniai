"""Round 13 Part 4(c) — request-coverage extraction (offline)."""

from __future__ import annotations

import sys
import tempfile
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
    from agent.request_coverage_check import (
        extract_file_coverage_items,
        missing_coverage_in_text,
        reset_request_coverage_state,
    )

    reset_request_coverage_state()
    q = (
        "Combine the CSVs in C:\\tmp\\x, find the best and worst month by "
        "revenue, and write a summary.md in the same folder."
    )
    items = extract_file_coverage_items(q)
    ids = {i["id"] for i in items}
    _check("has_best_worst_total", ids == {"best", "worst", "total"}, str(ids))

    body_bad = "## Summary\nBest: May 400\nWorst: April 90\n"
    missing = missing_coverage_in_text(q, body_bad)
    _check(
        "missing_total",
        [m["id"] for m in missing] == ["total"],
        str(missing),
    )
    body_ok = body_bad + "\nTotal revenue: 1240\n"
    missing2 = missing_coverage_in_text(q, body_ok)
    _check("complete", missing2 == [], str(missing2))

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
