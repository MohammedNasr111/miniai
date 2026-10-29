"""Fail if any app/design/*.png lacks MiniAI HWND provenance.

Provenance (any one):
  - sibling ``<stem>.capture.json`` or ``<stem>.json`` with title == \"MiniAI\"
    (written by scripts.miniai_capture)
  - entry in ``app/design/capture_summary.json`` with title == \"MiniAI\"
  - basename listed in ``app/design/legacy_manual_ok.txt`` (architect eye audit)

Exit 0 on success, 1 on failure. Prints FAIL lines to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN = PROJECT_ROOT / "app" / "design"
LEGACY = DESIGN / "legacy_manual_ok.txt"
SUMMARY = DESIGN / "capture_summary.json"
EXPECTED_TITLE = "MiniAI"


def _load_legacy() -> set[str]:
    if not LEGACY.is_file():
        return set()
    out: set[str] = set()
    for line in LEGACY.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.add(Path(s).name)
    return out


def _load_summary() -> dict[str, dict]:
    if not SUMMARY.is_file():
        return {}
    try:
        data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        # Either {"files": {...}} or direct name -> meta
        files = data.get("files") if "files" in data else data
        if isinstance(files, dict):
            return {str(k): v for k, v in files.items() if isinstance(v, dict)}
    return {}


def _title_ok(meta: dict) -> bool:
    return str(meta.get("title") or "").strip() == EXPECTED_TITLE


def _sibling_meta(png: Path) -> dict | None:
    candidates = [
        png.with_name(png.stem + ".capture.json"),
        png.with_name(png.stem + ".json"),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(meta, dict):
            return meta
    return None


def check() -> list[str]:
    if not DESIGN.is_dir():
        return [f"missing design dir: {DESIGN}"]
    legacy = _load_legacy()
    summary = _load_summary()
    fails: list[str] = []
    for png in sorted(DESIGN.glob("*.png")):
        name = png.name
        if name in legacy:
            continue
        sib = _sibling_meta(png)
        if sib is not None and _title_ok(sib):
            continue
        sum_meta = summary.get(name)
        if isinstance(sum_meta, dict) and _title_ok(sum_meta):
            continue
        fails.append(
            f"FAIL {name}: no MiniAI capture provenance "
            f"(need sibling .capture.json/.json, summary entry, or legacy_manual_ok.txt)"
        )
    return fails


def main() -> int:
    fails = check()
    if fails:
        for line in fails:
            print(line)
        print(f"check_design_pngs: {len(fails)} failure(s)")
        return 1
    n = len(list(DESIGN.glob("*.png"))) if DESIGN.is_dir() else 0
    print(f"check_design_pngs: OK ({n} png(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
