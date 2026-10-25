"""Offline tests for analyze_table (Round 6 Part 1)."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

import config.settings as settings  # noqa: E402

settings.FEATURE_ANALYZE_TABLE = True

from tools.filesystem.untrusted_file import BEGIN_FILE_MARKER, END_FILE_MARKER  # noqa: E402
from tools.registry import TOOL_FUNCTIONS, TOOL_TIERS  # noqa: E402
from tools.table.analyze import analyze_table  # noqa: E402
from security.gate import Tier  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _extract_json(text: str) -> dict:
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        raise AssertionError("no JSON block in tool output")
    return json.loads(m.group(1))


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="miniai_at_"))
    months = {
        "jan.csv": 100,
        "feb.csv": 250,
        "mar.csv": 180,
        "apr.csv": 90,
        "may.csv": 400,
        "jun.csv": 220,
    }
    paths = []
    for name, rev in months.items():
        p = root / name
        p.write_text(f"month,revenue\n{name[:3]},{rev}\n", encoding="utf-8")
        paths.append(str(p))

    # combine 6 CSVs + group/sum
    out = analyze_table(
        paths=paths,
        combine=True,
        group_by=["month"],
        aggregate={"revenue": "sum"},
        sort_by="revenue_sum",
        descending=True,
        limit=12,
    )
    _check("untrusted_wrap", BEGIN_FILE_MARKER in out and END_FILE_MARKER in out, "")
    data = _extract_json(out)
    _check("row_count_6", data["row_count"] == 6, str(data["row_count"]))
    _check("files_6", len(data["files"]) == 6, str(len(data["files"])))
    _check("total_all", data["totals"].get("all_revenue_sum") == 1240, str(data["totals"]))
    rows = data["rows"]
    _check("best_month", rows[0]["month"] == "may" and rows[0]["revenue_sum"] == 400, str(rows[0]))
    _check("worst_month", rows[-1]["month"] == "apr" and rows[-1]["revenue_sum"] == 90, str(rows[-1]))
    _check("md_has_table", "| month |" in out.lower() or "| month |" in out, out[:200])

    # bad column → clear error
    bad = analyze_table(paths=paths[:1], aggregate={"nope": "sum"})
    _check("bad_column", bad.startswith("Error:") and "nope" in bad.lower(), bad[:200])

    # formula-injection treated as plain text
    inj = root / "inject.csv"
    inj.write_text(
        "name,note\nAlice,=cmd|'/C calc'!A0\nBob,hello\n",
        encoding="utf-8",
    )
    inj_out = analyze_table(paths=[str(inj)], limit=10)
    inj_data = _extract_json(inj_out)
    notes = [r["note"] for r in inj_data["rows"]]
    _check(
        "formula_plain",
        any(str(n).startswith("=cmd") for n in notes),
        str(notes),
    )
    _check("formula_not_exec", "calc" in inj_out and "Error:" not in inj_out[:20], "")

    # size limit
    big = root / "big.csv"
    # Write a tiny header then claim size by writing large content
    # Use a real oversized file (~51 MB) would be slow; instead test the
    # guard by monkeypatching MAX_FILE_BYTES temporarily via module attr.
    import tools.table.analyze as mod

    saved = mod.MAX_FILE_BYTES
    try:
        mod.MAX_FILE_BYTES = 50
        tiny = root / "over.csv"
        tiny.write_text("a,b\n" + ("x," + "y" * 40 + "\n") * 5, encoding="utf-8")
        size_out = analyze_table(paths=[str(tiny)])
        _check(
            "size_limit",
            size_out.startswith("Error:") and "50" in size_out,
            size_out[:200],
        )
    finally:
        mod.MAX_FILE_BYTES = saved

    # too many files
    many = [str(root / "jan.csv")] * 21
    many_out = analyze_table(paths=many)
    _check("max_files", many_out.startswith("Error:") and "20" in many_out, many_out[:160])

    # xlsx round-trip
    try:
        import pandas as pd

        xlsx = root / "sheet.xlsx"
        pd.DataFrame({"month": ["jul"], "revenue": [50]}).to_excel(
            xlsx, index=False, engine="openpyxl"
        )
        x_out = analyze_table(
            paths=[str(xlsx)],
            aggregate={"revenue": "sum"},
        )
        x_data = _extract_json(x_out)
        _check(
            "xlsx_sum",
            x_data["totals"].get("revenue_sum") == 50
            or x_data["rows"][0].get("revenue_sum") == 50,
            str(x_data),
        )
    except Exception as exc:
        _check("xlsx_sum", False, str(exc))

    # filter contains
    filt = analyze_table(
        paths=paths,
        combine=True,
        filter={"column": "month", "op": "contains", "value": "a"},
    )
    f_data = _extract_json(filt)
    months_f = {r["month"] for r in f_data["rows"]}
    _check(
        "filter_contains",
        months_f <= {"jan", "mar", "apr", "may"} and "jan" in months_f,
        str(months_f),
    )

    # registry wiring
    _check("registry_fn", TOOL_FUNCTIONS.get("analyze_table") is analyze_table, "")
    _check("registry_tier", TOOL_TIERS.get("analyze_table") == Tier.AUTO_ALLOW, "")
    from tools.registry import TOOL_SCHEMAS

    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    _check("registry_schema", "analyze_table" in names, "")
    _check("maps_equal", set(TOOL_TIERS) == set(TOOL_FUNCTIONS), "")

    # feature flag off
    import config.settings as settings

    saved_flag = settings.FEATURE_ANALYZE_TABLE
    try:
        settings.FEATURE_ANALYZE_TABLE = False
        disabled = analyze_table(paths=paths[:1])
        _check("feature_off", "disabled" in disabled.lower(), disabled[:120])
    finally:
        settings.FEATURE_ANALYZE_TABLE = saved_flag

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
