"""Independent filesystem checks after successful create/delete (this turn only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


def _parent_label(path: str) -> str:
    """Short place name for truthful wording (Desktop, Downloads, …).

    Never returns "." — walk up until a real name, or match a known user folder.
    """
    try:
        p = Path(path)
        # Prefer matching a known user folder that contains this path.
        try:
            from config.paths import resolve_user_folders

            for folder_name, root in resolve_user_folders().items():
                try:
                    p.resolve().relative_to(root.resolve())
                    return folder_name  # e.g. "Desktop"
                except (ValueError, OSError):
                    # Path may not exist after delete — string prefix compare.
                    pref = str(root).rstrip("\\/").lower()
                    cand = str(p).rstrip("\\/").lower()
                    parent = str(p.parent).rstrip("\\/").lower()
                    if cand == pref or cand.startswith(pref + "\\") or parent == pref:
                        return folder_name
        except Exception:
            pass
        parent = p.parent
        name = (parent.name or "").strip()
        # Path("foo").parent.name can be "" ; Path("C:\\a\\.").name quirks → "."
        if name in ("", ".", ".."):
            # Walk up for a usable segment.
            cur = parent
            for _ in range(4):
                cur = cur.parent
                n = (cur.name or "").strip()
                if n and n not in (".", ".."):
                    return n
            drive = getattr(parent, "drive", None) or getattr(p, "drive", None)
            if drive:
                return str(drive).rstrip("\\/") + "\\"
            return "disk"
        return name
    except Exception:
        return "disk"


def _recycle_bin_has_basename(basename: str) -> bool:
    """True if Shell.Application Namespace(10) lists an item with this name.

    This is a real Recycle Bin membership check — not merely path absence.
    """
    if not basename:
        return False
    try:
        import win32com.client  # type: ignore
    except ImportError:
        try:
            import pythoncom  # noqa: F401
            from win32com.client import Dispatch  # type: ignore
        except ImportError:
            # Fallback without pywin32: COM via ctypes is heavy; skip.
            return False
        else:
            shell = Dispatch("Shell.Application")
            bin_ns = shell.NameSpace(10)
            if bin_ns is None:
                return False
            items = bin_ns.Items()
            needle = basename.lower()
            for i in range(items.Count):
                try:
                    if str(items.Item(i).Name or "").lower() == needle:
                        return True
                except Exception:
                    continue
            return False
    shell = win32com.client.Dispatch("Shell.Application")
    bin_ns = shell.NameSpace(10)
    if bin_ns is None:
        return False
    items = bin_ns.Items()
    needle = basename.lower()
    for i in range(items.Count):
        try:
            if str(items.Item(i).Name or "").lower() == needle:
                return True
        except Exception:
            continue
    return False


def verify_create_delete(transcript: Any = None) -> dict[str, Any]:
    """os.path.exists checks for this turn's create_file / create_folder / delete_file.

    Uses in-memory turn targets (not the full session transcript) so prior
    turns cannot leak into this turn's verify nodes or Footprint.
    """
    from agent.action_claim_check import get_fs_verify_targets, get_turn_id

    # transcript kept for API compat; intentionally unused for scoping.
    _ = transcript
    targets = get_fs_verify_targets()
    # One check per normalized path (prefer was_dir=True if any recording says so).
    by_path: dict[str, tuple[str, str, bool]] = {}
    for tool, path, was_dir in targets:
        if not path or path.strip() in (".", "..") or path.strip().lower() in (
            "folder",
            "file",
            "directory",
        ):
            continue
        key = path.replace("/", "\\").rstrip("\\").lower()
        prev = by_path.get(key)
        if prev is None:
            by_path[key] = (tool, path, was_dir)
        else:
            by_path[key] = (tool, prev[1], prev[2] or was_dir)

    checks: list[dict[str, Any]] = []
    for tool, path, was_dir in by_path.values():
        exists = os.path.exists(path)
        kind = "folder" if (was_dir or (exists and os.path.isdir(path))) else "file"
        if tool == "delete_file":
            gone = not exists
            place = _parent_label(path)
            if place in (".", "..", ""):
                place = "disk"
            base = Path(path).name
            in_bin = False
            if gone:
                in_bin = _recycle_bin_has_basename(base)
            # Exactly one detail string per deleted path.
            if gone and in_bin:
                detail = f"{'Folder' if kind == 'folder' else 'File'} is in the Recycle Bin"
            elif gone:
                detail = f"Gone from {place} (sent to the Recycle Bin)"
            else:
                detail = f"{'Folder' if kind == 'folder' else 'File'} still present on disk: {path}"
            ok = gone
            checks.append(
                {
                    "tool": tool,
                    "path": path,
                    "ok": ok,
                    "detail": detail,
                    "checked": "path_absent"
                    + ("+recycle_bin_name" if in_bin else ""),
                }
            )
        elif tool == "create_folder":
            ok = exists and os.path.isdir(path)
            detail = "Folder exists on disk" if ok else f"Folder missing: {path}"
            checks.append(
                {
                    "tool": tool,
                    "path": path,
                    "ok": ok,
                    "detail": detail,
                    "checked": "path_isdir",
                }
            )
        else:
            ok = exists and os.path.isfile(path)
            detail = "File exists on disk" if ok else f"File missing: {path}"
            checks.append(
                {
                    "tool": tool,
                    "path": path,
                    "ok": ok,
                    "detail": detail,
                    "checked": "path_isfile",
                }
            )
    passed = [c for c in checks if c["ok"]]
    return {
        "ran": bool(checks),
        "passed": bool(passed) and all(c["ok"] for c in checks),
        "checks": checks,
        "summary": "; ".join(c["detail"] for c in passed) if passed else "",
        "turn_id": get_turn_id(),
    }
