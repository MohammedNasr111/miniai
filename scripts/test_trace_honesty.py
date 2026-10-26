"""Offline: denied labels, path middle-ellipsis, no past-tense on decline."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0

_PAST = re.compile(
    r"\b(Created|Wrote|Moved|Deleted|Ran|Saved|Installed|Imported|Exported|Restored)\b"
)


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from app.action_classes import (
        denied_label_for,
        ellipsis_path,
        label_for,
    )

    for tool in (
        "create_file",
        "write_file",
        "move_file",
        "move_files",
        "delete_file",
        "run_tests",
    ):
        lab = denied_label_for(tool)
        check(f"denied_muted_{tool}", "declined" in lab.lower() and lab.startswith("Didn't"))
        check(f"denied_no_past_{tool}", not _PAST.search(lab), lab)
        # Done label must differ and use past tense for contrast
        done = label_for(tool, done=True)
        check(f"done_differs_{tool}", done != lab and bool(_PAST.search(done) or "Moved" in done or "files" in done.lower()), done)

    long_path = r"C:\Users\mohdc\OneDrive\Documents\Projects\Nested\Deep\file.txt"
    short = ellipsis_path(long_path, max_len=40)
    check("ellipsis_keeps_drive", short.startswith("C:\\"), short)
    check("ellipsis_has_middle", "…" in short, short)
    check("ellipsis_keeps_tail", short.endswith("file.txt") or "file.txt" in short, short)
    check("ellipsis_not_tail_only", not short.startswith("Projects"), short)

    # syncSteps order: action node before ticket — assert in app.js source
    js = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    check(
        "sync_places_ticket_after_step",
        "dataset.tool === tool" in js and "t._placed" in js,
        "ticket re-insert after matching step",
    )
    check("ticket_sets_data_tool", "dataset.tool = req.action" in js)

    css = (ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    check("denied_css", 'data-k="denied"' in css)
    check("ticket_perforation", "radial-gradient" in css and ".ticket::before" in css)

    # webview denied path
    wa = (ROOT / "app" / "webview_approver.py").read_text(encoding="utf-8")
    check(
        "webview_denied_label",
        "denied_label_for" in wa and ('["k"] = "denied"' in wa or "['k'] = 'denied'" in wa),
    )

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
