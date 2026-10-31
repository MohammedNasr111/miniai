"""Live turn phase labels (Round 12 Part 3).

Elapsed seconds are shown in the UI; this module only names the phase from
tool/approval/checking state. No time-remaining estimates.
"""

from __future__ import annotations

from typing import Any, Optional


def _short_path(path: str, *, max_len: int = 48) -> str:
    s = str(path or "").strip()
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    # Prefer keeping drive + last folders.
    parts = s.replace("/", "\\").split("\\")
    if len(parts) >= 3:
        head = parts[0] + "\\"
        if parts[0].endswith(":"):
            head = parts[0] + "\\"
        tail = "\\".join(parts[-2:])
        out = head + "…\\" + tail
        if len(out) <= max_len:
            return out
        return "…\\" + tail[-(max_len - 2) :]
    return "…" + s[-(max_len - 1) :]


def _path_from_args(args: Optional[dict[str, Any]]) -> str:
    if not isinstance(args, dict):
        return ""
    for key in ("path", "folder", "directory", "dir", "target", "src", "dst"):
        v = args.get(key)
        if v:
            return str(v)
    paths = args.get("paths")
    if isinstance(paths, (list, tuple)) and paths:
        return str(paths[0])
    return ""


def phase_from_turn(
    *,
    waiting: bool = False,
    checking: bool = False,
    steps: Optional[list[dict[str, Any]]] = None,
    warming: bool = False,
    thinking: bool = False,
    writing: bool = False,
) -> dict[str, Any]:
    """Return {label, show_elapsed, kind} for the turn header."""
    if waiting:
        return {
            "label": "Waiting for your approval",
            "show_elapsed": False,
            "kind": "approval",
        }
    if checking:
        return {
            "label": "Checking the answer…",
            "show_elapsed": False,
            "kind": "checking",
        }
    if writing:
        return {"label": "Writing…", "show_elapsed": True, "kind": "writing"}
    if thinking:
        return {"label": "Thinking…", "show_elapsed": True, "kind": "thinking"}

    for step in reversed(list(steps or [])):
        if not step.get("running"):
            continue
        tool = str(step.get("tool") or "")
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        path = _path_from_args(args)
        if not path and step.get("detail"):
            # detail sometimes holds a path
            d = str(step.get("detail") or "")
            if ":\\" in d or d.startswith("\\\\") or d.startswith("/"):
                path = d
        if path and tool in {
            "read_file",
            "list_directory",
            "search_files",
            "create_file",
            "create_folder",
            "write_file",
            "move_file",
            "move_files",
            "delete_file",
            "analyze_table",
            "index_pdf",
            "read_pdf",
        }:
            return {
                "label": f"Reading {_short_path(path)}…",
                "show_elapsed": True,
                "kind": "tool",
                "path": path,
            }
        name = str(step.get("name") or tool or "Working").rstrip(".")
        if not name.endswith("…"):
            name = name + "…"
        return {"label": name, "show_elapsed": True, "kind": "tool"}

    if warming:
        return {"label": "Warming up…", "show_elapsed": True, "kind": "warming"}
    return {"label": "Working…", "show_elapsed": True, "kind": "working"}
