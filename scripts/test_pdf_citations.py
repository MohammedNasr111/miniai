"""Offline tests for Round 6 Part 4 PDF page citations."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

import config.settings as settings  # noqa: E402

settings.FEATURE_PDF_CITATIONS = True

from agent.pdf_citations import (  # noqa: E402
    append_pdf_citations,
    parse_knowledge_hits,
    pick_citations,
    token_overlap,
    tokenize,
)

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    clause = (
        "WARRANTY CLAUSE: This product is covered for twenty-four (24) months "
        "from the date of purchase against manufacturing defects."
    )
    hits = [
        {
            "source_path": r"C:\tmp\warranty.pdf",
            "page_number": 1,
            "content": "Page 1 cover brochure fluff unrelated widgets.",
        },
        {
            "source_path": r"C:\tmp\warranty.pdf",
            "page_number": 2,
            "content": "Page 2 intro about the company history only.",
        },
        {
            "source_path": r"C:\tmp\warranty.pdf",
            "page_number": 3,
            "content": clause,
        },
        {
            "source_path": r"C:\tmp\other.pdf",
            "page_number": 1,
            "content": "Completely different topic about tropical fish tanks.",
        },
    ]
    tool_json = json.dumps(hits)
    parsed = parse_knowledge_hits([tool_json, "not json", "{}"])
    _check("parse_hits", len(parsed) == 4, str(len(parsed)))

    answer = (
        "According to the warranty, the product is covered for twenty-four "
        "months against manufacturing defects."
    )
    # Overlap with page 3 should dominate
    ov3 = token_overlap(answer, clause)
    ov1 = token_overlap(answer, hits[0]["content"])
    _check("overlap_page3_high", ov3 > ov1 and ov3 >= 0.12, f"ov3={ov3:.3f} ov1={ov1:.3f}")

    cites = pick_citations(answer, hits, threshold=0.12, max_citations=3)
    _check("pick_page3", cites and cites[0][1] == 3, str(cites))
    _check("pick_file", cites and cites[0][0] == "warranty.pdf", str(cites))
    _check("max_3", len(cites) <= 3, str(cites))

    out, meta = append_pdf_citations(
        answer, [tool_json], tools_used={"search_knowledge"}
    )
    _check(
        "append_line",
        "Source: warranty.pdf, page 3" in out,
        out[-200:],
    )
    _check("meta_applied", meta.get("applied") is True, str(meta))

    # Low overlap → no citation
    weak = "The sky is blue today."
    out2, meta2 = append_pdf_citations(
        weak, [tool_json], tools_used={"search_knowledge"}
    )
    _check(
        "no_weak",
        "Source:" not in out2 and meta2.get("applied") is False,
        out2[-80:],
    )

    # Idempotent
    out3, meta3 = append_pdf_citations(
        out, [tool_json], tools_used={"search_knowledge"}
    )
    _check(
        "idempotent",
        out3.count("Source: warranty.pdf, page 3") == 1,
        str(meta3),
    )

    # Feature flag off
    import config.settings as settings

    saved = settings.FEATURE_PDF_CITATIONS
    try:
        settings.FEATURE_PDF_CITATIONS = False
        out4, meta4 = append_pdf_citations(
            answer, [tool_json], tools_used={"search_knowledge"}
        )
        _check("flag_off", "Source:" not in out4 and meta4.get("applied") is False, "")
    finally:
        settings.FEATURE_PDF_CITATIONS = saved

    _check("tokenize", "twenty" in tokenize(clause) and "the" not in tokenize(clause))

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
