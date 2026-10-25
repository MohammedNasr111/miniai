"""Round 7 offline checks: tool classes, footprint, tickets, no middle dots."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global FAILURES
    if cond:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from app.action_classes import (
        TOOL_CLASS,
        VERIFY_EVENTS,
        assert_no_middle_dots,
        class_for,
        label_for,
        ticket_copy,
    )
    from app.footprint import (
        NO_UPLOAD_LINE,
        empty_footprint,
        record_tool,
        record_verify,
        ui_payload,
    )
    from tools.registry import TOOL_SCHEMAS

    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    missing = [n for n in names if n not in TOOL_CLASS]
    check("tool_class_covers_registry", not missing, f"missing={missing}")

    # Spot-check classes from the task brief
    check("list_directory_read", class_for("list_directory") == "read")
    check("web_research_out", class_for("web_research") == "out")
    check("ws_write_change", class_for("ws_write") == "change")
    check("delete_danger", class_for("delete_file") == "danger")
    check("quote_verify", class_for("quote_check") == "verify")
    for ev in VERIFY_EVENTS:
        check(f"verify_{ev}", class_for(ev) == "verify")

    # Labels never expose raw tool names for known tools
    for n in names:
        lab = label_for(n, done=True)
        check(f"label_no_raw_{n}", n not in lab or " " in lab, lab)

    # Footprint classes
    doc = {"footprint": empty_footprint()}
    record_tool(doc, "web_research", {"question": "Windows update"})
    record_tool(doc, "fetch_url", {"url": "https://example.com/a"})
    record_tool(doc, "list_directory", {"path": r"C:\Users\x\Downloads"})
    record_tool(doc, "read_file", {"path": r"C:\Users\x\a.txt"})
    record_tool(doc, "move_files", {"moves": [{"src": "a", "dest": "b"}]})
    record_tool(doc, "delete_file", {"path": r"C:\Users\x\dup.exe"})
    record_verify(doc, "Move claim matched the disk", status="pass")
    fp = doc["footprint"]
    check("fp_left_2", len(fp["left"]) == 2)
    check("fp_read_2", len(fp["read"]) == 2)
    check("fp_changed_2", len(fp["changed"]) == 2)
    check("fp_verified_1", len(fp["verified"]) == 1)
    check("fp_assert_no_upload", fp["assert_no_upload"] is True)
    check("fp_delete_recycle", "Recycle Bin" in fp["changed"][-1]["label"])
    ui = ui_payload(fp)
    check("fp_ui_no_upload_line", ui["no_upload"] == NO_UPLOAD_LINE)
    check("fp_ui_assert", ui["assert_no_upload"] is True)

    # Ticket labels
    d = ticket_copy("delete_file", r"Move to Recycle Bin: C:\x\a.exe")
    check("ticket_delete_approve", d["approve"] == "Delete file")
    check("ticket_delete_deny", d["deny"] == "Keep it")
    check("ticket_delete_kind", d["kind"] == "danger")
    m = ticket_copy(
        "move_files",
        "Move 5 file(s):\n  a -> b\n  c -> d\n  e -> f\n  g -> h\n  i -> j",
    )
    check("ticket_move_approve", m["approve"].startswith("Move"))
    check("ticket_move_deny", m["deny"] == "Don't move")
    check("ticket_no_generic_approve", "Approve" not in d["approve"])
    check("ticket_no_generic_deny", d["deny"] != "Deny")

    # No middle dots in UI strings we emit
    samples = [
        label_for("web_research", done=True),
        label_for("list_directory", done=False),
        d["approve"],
        d["deny"],
        d["collapsed_ok"],
        NO_UPLOAD_LINE,
        ui["context_label"],
        "Qwen3 30B, on this PC",
        "16.5 of 23.6 GB",
        "Nothing left this PC",
    ]
    for s in samples:
        try:
            assert_no_middle_dots(s)
            check(f"no_middot:{s[:40]}", True)
        except AssertionError as exc:
            check(f"no_middot:{s[:40]}", False, str(exc))

    # Scan UI source files for middle-dot character
    for rel in ("app/ui/app.js", "app/ui/index.html", "app/ui/styles.css"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        check(f"source_no_middot_{rel}", "·" not in text and "\u00b7" not in text)

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
