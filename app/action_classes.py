"""Map every registered tool to a run-log action class and plain-English copy.

Classes (match app/design/miniai_v2_concept.html):
  read   — glacier, hollow circle (on this PC)
  out    — lilac, dashed circle (left this PC)
  change — amber, filled square
  danger — brick, hollow circle (deletes)
  verify — verdigris, filled circle (guards / checks)
"""

from __future__ import annotations

from typing import Any, Optional

# tool_name -> class key used as data-k on .step
TOOL_CLASS: dict[str, str] = {
    # read on this PC
    "list_directory": "read",
    "read_file": "read",
    "search_files": "read",
    "search_knowledge": "read",
    "index_documents": "read",
    "desktop_list_windows": "read",
    "desktop_read_window": "read",
    "ws_read": "read",
    "ws_list": "read",
    "analyze_table": "read",
    "ws_find_project": "read",
    "search_memory": "read",
    "list_memories": "read",
    "workspace_history": "read",
    "calculate": "read",
    "browser_observe": "read",
    # left this PC
    "web_research": "out",
    "web_search": "out",
    "fetch_url": "out",
    "browser_open": "out",
    "browser_click": "out",
    "browser_type": "out",
    # changes things
    "create_file": "change",
    "write_file": "change",
    "move_file": "change",
    "move_files": "change",
    "ws_write": "change",
    "ws_edit": "change",
    "desktop_begin_task": "change",
    "desktop_set_text": "change",
    "desktop_insert_text": "change",
    "desktop_press": "change",
    "install_package": "change",
    "run_file": "change",
    "run_code": "change",
    "run_tests": "change",
    "save_memory": "change",
    "workspace_import": "change",
    "workspace_export": "change",
    "workspace_restore": "change",
    # deletes
    "delete_file": "danger",
}

# Synthetic verify / guard events (not in TOOL_SCHEMAS)
VERIFY_EVENTS = frozenset(
    {
        "quote_check",
        "run_claim_check",
        "action_claim_check",
        "price_check",
        "recency_note",
        "injection_notice",
        "answer_check",
    }
)

# Plain labels (done, in_progress) — never expose raw tool names in the UI.
_LABELS: dict[str, tuple[str, str]] = {
    "list_directory": ("Listing a folder", "Listed a folder"),
    "read_file": ("Reading a file", "Read a file"),
    "search_files": ("Searching files", "Searched files"),
    "search_knowledge": ("Searching knowledge", "Searched knowledge"),
    "index_documents": ("Indexing documents", "Indexed documents"),
    "desktop_list_windows": ("Listing windows", "Listed windows"),
    "desktop_read_window": ("Reading a window", "Read a window"),
    "ws_read": ("Reading a workspace file", "Read a workspace file"),
    "ws_list": ("Listing the workspace", "Listed the workspace"),
    "analyze_table": ("Analyzing a table", "Analyzed a table"),
    "ws_find_project": ("Finding a project", "Found a project"),
    "search_memory": ("Searching memory", "Searched memory"),
    "list_memories": ("Listing memories", "Listed memories"),
    "workspace_history": ("Checking history", "Checked history"),
    "calculate": ("Calculating", "Calculated"),
    "browser_observe": ("Looking at the page", "Looked at the page"),
    "web_research": ("Searching the web", "Searched the web"),
    "web_search": ("Searching the web", "Searched the web"),
    "fetch_url": ("Fetching a page", "Fetched a page"),
    "browser_open": ("Opening a page", "Opened a page"),
    "browser_click": ("Clicking on the page", "Clicked on the page"),
    "browser_type": ("Typing on the page", "Typed on the page"),
    "create_file": ("Creating a file", "Created a file"),
    "write_file": ("Writing a file", "Wrote a file"),
    "move_file": ("Moving a file", "Moved a file"),
    "move_files": ("Moving files", "Moved files"),
    "ws_write": ("Writing a workspace file", "Wrote a workspace file"),
    "ws_edit": ("Editing a workspace file", "Edited a workspace file"),
    "desktop_begin_task": ("Starting a desktop task", "Started a desktop task"),
    "desktop_set_text": ("Setting text", "Set text"),
    "desktop_insert_text": ("Inserting text", "Inserted text"),
    "desktop_press": ("Pressing keys", "Pressed keys"),
    "install_package": ("Installing a package", "Installed a package"),
    "run_file": ("Running a file", "Ran a file"),
    "run_code": ("Running code", "Ran code"),
    "run_tests": ("Running tests", "Ran tests"),
    "save_memory": ("Saving a memory", "Saved a memory"),
    "workspace_import": ("Importing a project", "Imported a project"),
    "workspace_export": ("Exporting a project", "Exported a project"),
    "workspace_restore": ("Restoring files", "Restored files"),
    "delete_file": ("Deleting a file", "Deleted a file"),
    "quote_check": ("Checking quotes", "Checked every quote against the pages"),
    "run_claim_check": ("Checking the claim", "Checked the claim against what happened"),
    "action_claim_check": (
        "Checking the claim",
        "Checked the claim against what actually happened",
    ),
    "price_check": ("Checking prices", "Checked price estimates"),
    "recency_note": ("Checking dates", "Noted a stale page"),
    "injection_notice": ("Noting page instructions", "Noted instructions found in a page"),
    "answer_check": (
        "Checking the answer against sources",
        "Checked the answer against sources",
    ),
}


def class_for(tool_or_event: str) -> str:
    if tool_or_event in VERIFY_EVENTS:
        return "verify"
    return TOOL_CLASS.get(tool_or_event, "change")


def label_for(tool_or_event: str, *, done: bool) -> str:
    pair = _LABELS.get(tool_or_event)
    if pair is None:
        # Fallback without exposing snake_case if we can help it.
        nice = tool_or_event.replace("_", " ").strip()
        return nice.capitalize() if done else (nice.capitalize() + "…")
    return pair[1] if done else pair[0]


def format_duration(seconds: float) -> str:
    s = max(0.0, float(seconds))
    if s < 10:
        return f"{s:.1f} s".replace(".0 s", " s") if s >= 1 else f"{s:.1f} s"
    whole = int(round(s))
    if whole < 60:
        return f"{whole} s"
    m, rem = divmod(whole, 60)
    if m < 60:
        return f"{m} m {rem} s" if rem else f"{m} m"
    h, rem_m = divmod(m, 60)
    return f"{h} h {rem_m} m"


def _short_path(path: Any) -> str:
    s = str(path or "").strip()
    if not s:
        return ""
    # Prefer a short tail for display.
    parts = s.replace("/", "\\").split("\\")
    if len(parts) <= 3:
        return s
    return "\\".join(parts[-3:])


def detail_for(tool: str, args: Optional[dict[str, Any]] = None) -> str:
    """One-line detail under the node label. Never JSON."""
    args = args or {}
    if tool == "list_directory":
        p = _short_path(args.get("path"))
        return p or "Folder listing"
    if tool in ("read_file", "ws_read", "create_file", "write_file", "delete_file"):
        return _short_path(args.get("path")) or "A file"
    if tool == "move_file":
        return f"{_short_path(args.get('src'))} → {_short_path(args.get('dest'))}"
    if tool == "move_files":
        moves = args.get("moves") or []
        n = len(moves) if isinstance(moves, list) else 0
        return f"{n} file{'s' if n != 1 else ''}"
    if tool in ("web_research", "web_search"):
        q = str(args.get("question") or args.get("query") or "").strip()
        return (q[:80] + "…") if len(q) > 80 else q
    if tool in ("fetch_url", "browser_open"):
        return str(args.get("url") or "")[:100]
    if tool in ("ws_write", "ws_edit"):
        return _short_path(args.get("path")) or "Workspace file"
    if tool == "run_tests":
        return _short_path(args.get("path") or args.get("root") or ".") or "Tests"
    if tool == "analyze_table":
        paths = args.get("paths") or []
        if isinstance(paths, list) and paths:
            return f"{len(paths)} file{'s' if len(paths) != 1 else ''}"
        return "Table"
    if tool == "save_memory":
        return "Saved to long-term memory"
    if tool == "search_knowledge":
        q = str(args.get("query") or "").strip()
        return (q[:80] + "…") if len(q) > 80 else (q or "Knowledge search")
    return ""


def ticket_copy(action: str, description: str = "") -> dict[str, str]:
    """Approve / deny button labels + consequence for a permission ticket."""
    a = (action or "").strip()
    desc = description or ""
    paths = _paths_from_description(desc)
    if a == "delete_file":
        return {
            "kind": "danger",
            "heading": "Delete 1 file",
            "consequence": "It goes to the Recycle Bin, so you can restore it.",
            "approve": "Delete file",
            "deny": "Keep it",
            "paths": "\n".join(paths) if paths else desc.strip(),
            "collapsed_ok": "You approved: delete 1 file",
            "collapsed_no": "You kept the file",
        }
    if a == "move_files":
        n = 0
        for line in desc.splitlines():
            if "->" in line or "→" in line:
                n += 1
        if n == 0:
            n = max(1, desc.lower().count("move"))
        return {
            "kind": "change",
            "heading": f"Move {n} file{'s' if n != 1 else ''}",
            "consequence": "Files leave their current folders and appear at the new paths.",
            "approve": f"Move {n} file{'s' if n != 1 else ''}",
            "deny": "Don't move",
            "paths": "\n".join(paths) if paths else desc.strip(),
            "collapsed_ok": f"You approved: move {n} file{'s' if n != 1 else ''}",
            "collapsed_no": "You kept the files where they were",
        }
    if a == "move_file":
        return {
            "kind": "change",
            "heading": "Move 1 file",
            "consequence": "The file leaves its current folder and appears at the new path.",
            "approve": "Move file",
            "deny": "Don't move",
            "paths": "\n".join(paths) if paths else desc.strip(),
            "collapsed_ok": "You approved: move 1 file",
            "collapsed_no": "You kept the file where it was",
        }
    if a in ("write_file", "create_file"):
        verb = "Create" if a == "create_file" or "did not exist" in desc.lower() else "Write"
        return {
            "kind": "change",
            "heading": f"{verb} a file",
            "consequence": (
                "A backup of the current file will be kept."
                if "Overwrite" in desc or "backup" in desc.lower()
                else "A new file will be created on this PC."
            ),
            "approve": f"{verb} file",
            "deny": "Don't write",
            "paths": "\n".join(paths) if paths else desc.strip(),
            "collapsed_ok": f"You approved: {verb.lower()} a file",
            "collapsed_no": "You cancelled the write",
        }
    if a == "run_tests":
        return {
            "kind": "change",
            "heading": "Run tests",
            "consequence": "Pytest runs in the isolated runner on this PC.",
            "approve": "Run tests",
            "deny": "Don't run",
            "paths": desc.strip(),
            "collapsed_ok": "You approved: run tests",
            "collapsed_no": "You skipped the tests",
        }
    if a in ("run_file", "run_code", "install_package"):
        headings = {
            "run_file": ("Run a file", "Run file", "Don't run"),
            "run_code": ("Run code", "Run code", "Don't run"),
            "install_package": ("Install a package", "Install", "Don't install"),
        }
        h, ap, dn = headings[a]
        return {
            "kind": "change",
            "heading": h,
            "consequence": "This runs on this PC inside the isolated runner when available.",
            "approve": ap,
            "deny": dn,
            "paths": desc.strip(),
            "collapsed_ok": f"You approved: {h.lower()}",
            "collapsed_no": f"You chose: {dn.lower()}",
        }
    # Generic CONFIRM
    nice = a.replace("_", " ")
    return {
        "kind": "change",
        "heading": nice[:1].upper() + nice[1:] if nice else "Allow action",
        "consequence": "This will change something on this PC.",
        "approve": nice[:1].upper() + nice[1:] if nice else "Allow",
        "deny": "Don't allow",
        "paths": desc.strip(),
        "collapsed_ok": f"You approved: {nice}",
        "collapsed_no": "You denied the action",
    }


def _paths_from_description(desc: str) -> list[str]:
    lines: list[str] = []
    for raw in (desc or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("---"):
            break
        # Common shapes from fs_tools
        for prefix in (
            "Move to Recycle Bin: ",
            "Create new file: ",
            "Create file (did not exist): ",
            "Overwrite existing file: ",
            "from: ",
            "to:   ",
            "to: ",
        ):
            if line.startswith(prefix):
                lines.append(line[len(prefix) :].strip())
                break
        else:
            if "->" in line:
                lines.append(line)
            elif ":\\" in line or line.startswith("/") or "\\" in line:
                # Likely a path line in a batch move list
                if "Move " not in line and "file(s)" not in line:
                    lines.append(line)
    return lines[:40]


def is_outbound(tool: str) -> bool:
    return class_for(tool) == "out"


def assert_no_middle_dots(text: str) -> None:
    """UI strings must not use middle-dot separators (·)."""
    if "·" in (text or "") or "\u00b7" in (text or ""):
        raise AssertionError(f"middle-dot forbidden in UI string: {text!r}")
