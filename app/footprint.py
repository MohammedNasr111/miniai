"""Per-chat footprint ledger: what left / was read / changed / verified."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.action_classes import class_for, is_outbound

# Design invariant: MiniAI never uploads local files or memories to the web.
NO_UPLOAD_LINE = "No files or memories were uploaded."

CONTEXT_TOKEN_BUDGET = 16_000


def empty_footprint() -> dict[str, Any]:
    return {
        "left": [],  # {label, time, kind: search|fetch}
        "read": [],  # {label, detail, time}
        "changed": [],  # {label, time, recycle?}
        "verified": [],  # {label, status: pass|correction}
        "context_tokens": 0,
        "context_budget": CONTEXT_TOKEN_BUDGET,
        "assert_no_upload": True,
    }


def _now_hm() -> str:
    return datetime.now().astimezone().strftime("%H:%M")


def ensure_footprint(doc: dict[str, Any]) -> dict[str, Any]:
    fp = doc.get("footprint")
    if not isinstance(fp, dict):
        fp = empty_footprint()
        doc["footprint"] = fp
    fp.setdefault("left", [])
    fp.setdefault("read", [])
    fp.setdefault("changed", [])
    fp.setdefault("verified", [])
    fp.setdefault("context_tokens", 0)
    fp.setdefault("context_budget", CONTEXT_TOKEN_BUDGET)
    fp["assert_no_upload"] = True
    return fp


def record_tool(
    doc: Optional[dict[str, Any]],
    tool: str,
    args: Optional[dict[str, Any]] = None,
    *,
    ok: bool = True,
    when: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Append a footprint entry for a completed tool call. Returns the footprint."""
    if doc is None:
        return None
    fp = ensure_footprint(doc)
    args = args or {}
    t = when or _now_hm()
    kind = class_for(tool)

    # Synthetic sub-step from web_research progress (not a registered tool).
    if tool == "web_pages_read":
        try:
            n = int(args.get("count") or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            fp["read"].append(
                {
                    "label": f"{n} web page{'s' if n != 1 else ''} (untrusted)",
                    "detail": "untrusted",
                    "time": t,
                }
            )
        fp["assert_no_upload"] = True
        return fp

    if kind == "out" or is_outbound(tool):
        if tool in ("web_research", "web_search"):
            q = str(args.get("question") or args.get("query") or "").strip()
            label = f"Search: {q}" if q else "Search"
            fp["left"].append({"label": label, "time": t, "kind": "search"})
            # Pages read during research also count under "Read on this PC".
            n_pages = args.get("pages_read")
            try:
                n = int(n_pages) if n_pages is not None else 0
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                fp["read"].append(
                    {
                        "label": f"{n} web page{'s' if n != 1 else ''} (untrusted)",
                        "detail": "untrusted",
                        "time": t,
                    }
                )
        else:
            url = str(args.get("url") or "").strip()
            label = f"Fetch: {url}" if url else "Fetched a page"
            fp["left"].append({"label": label, "time": t, "kind": "fetch"})
        # Invariant: outbound never means upload.
        fp["assert_no_upload"] = True
        return fp

    if kind == "read":
        label, detail = _read_label(tool, args)
        fp["read"].append({"label": label, "detail": detail, "time": t})
        return fp

    if kind in ("change", "danger") and ok:
        label = _change_label(tool, args)
        entry: dict[str, Any] = {"label": label, "time": t}
        if tool == "delete_file":
            entry["recycle"] = True
            if "Recycle Bin" not in label:
                entry["label"] = label + " to Recycle Bin"
        fp["changed"].append(entry)
        return fp

    return fp


def record_verify(
    doc: Optional[dict[str, Any]],
    label: str,
    *,
    status: str = "pass",
    when: Optional[str] = None,
    turn_id: str = "",
) -> Optional[dict[str, Any]]:
    if doc is None:
        return None
    fp = ensure_footprint(doc)
    # Count each (turn_id, label) once — prevents cross-turn re-counts.
    if turn_id:
        for existing in fp.get("verified") or []:
            if (
                existing.get("turn_id") == turn_id
                and existing.get("label") == label
            ):
                return fp
    entry: dict[str, Any] = {
        "label": label,
        "status": status,
        "time": when or _now_hm(),
    }
    if turn_id:
        entry["turn_id"] = turn_id
    fp["verified"].append(entry)
    return fp


def set_context_tokens(doc: Optional[dict[str, Any]], used: int) -> None:
    if doc is None:
        return
    fp = ensure_footprint(doc)
    fp["context_tokens"] = max(0, int(used))
    fp["context_budget"] = CONTEXT_TOKEN_BUDGET


def counts(fp: dict[str, Any]) -> dict[str, int]:
    return {
        "left": len(fp.get("left") or []),
        "read": len(fp.get("read") or []),
        "changed": len(fp.get("changed") or []),
        "verified": len(fp.get("verified") or []),
    }


def _read_label(tool: str, args: dict[str, Any]) -> tuple[str, str]:
    if tool == "list_directory":
        p = str(args.get("path") or "folder")
        return (f"{p} (folder listing)", "")
    if tool in ("read_file", "ws_read"):
        return (str(args.get("path") or "file"), "file")
    if tool in ("fetch_url", "browser_open", "browser_observe"):
        return ("Web page", "untrusted")
    if tool == "search_knowledge":
        return ("Knowledge search", str(args.get("query") or "")[:40])
    if tool == "analyze_table":
        n = len(args.get("paths") or []) if isinstance(args.get("paths"), list) else 0
        return (f"Table ({n} file{'s' if n != 1 else ''})", "")
    if tool == "desktop_read_window":
        return ("Desktop window", "untrusted")
    return (tool.replace("_", " "), "")


def _change_label(tool: str, args: dict[str, Any]) -> str:
    if tool == "delete_file":
        path = args.get("path")
        is_folder = bool(args.get("was_dir"))
        if path and not is_folder:
            try:
                from pathlib import Path as _P

                is_folder = _P(str(path)).is_dir()
            except Exception:
                pass
        noun = "folder" if is_folder else "file"
        return f"Deleted {noun} {path or ('a ' + noun)}"
    if tool == "move_files":
        moves = args.get("moves") or []
        n = len(moves) if isinstance(moves, list) else 0
        return f"Moved {n} file{'s' if n != 1 else ''}"
    if tool == "move_file":
        return f"Moved {args.get('src') or 'a file'}"
    if tool == "create_folder":
        return f"Created folder {args.get('path') or 'a folder'}"
    if tool in ("create_file", "write_file", "ws_write"):
        return f"Wrote {args.get('path') or 'a file'}"
    if tool == "ws_edit":
        return f"Edited {args.get('path') or 'a file'}"
    if tool == "install_package":
        return f"Installed {args.get('package') or 'a package'}"
    if tool in ("desktop_set_text", "desktop_insert_text", "desktop_type"):
        return "Typed into a window"
    if tool == "save_memory":
        return "Saved a memory"
    return tool.replace("_", " ").capitalize()


def ui_payload(fp: dict[str, Any]) -> dict[str, Any]:
    """Shape consumed by the footprint panel in the UI."""
    c = counts(fp)
    used = int(fp.get("context_tokens") or 0)
    budget = int(fp.get("context_budget") or CONTEXT_TOKEN_BUDGET)
    pct = int(round(100 * used / budget)) if budget else 0
    return {
        "left": list(fp.get("left") or []),
        "read": list(fp.get("read") or []),
        "changed": list(fp.get("changed") or []),
        "verified": list(fp.get("verified") or []),
        "counts": c,
        "no_upload": NO_UPLOAD_LINE,
        "assert_no_upload": bool(fp.get("assert_no_upload", True)),
        "context_tokens": used,
        "context_budget": budget,
        "context_pct": min(100, pct),
        "context_label": f"{used / 1000:.1f}k of {budget // 1000}k tokens",
    }
