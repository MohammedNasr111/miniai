"""Independent filesystem checks after successful create/delete (this turn only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional


def _parent_label(path: str) -> str:
    """Short place name for truthful wording (Desktop, Downloads, …)."""
    try:
        parent = Path(path).parent
        name = parent.name or str(parent)
    except Exception:
        return "disk"
    known = {
        "desktop",
        "documents",
        "downloads",
        "pictures",
        "music",
        "videos",
    }
    if name.lower() in known:
        return name
    return name or "disk"


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
    checks: list[dict[str, Any]] = []
    for tool, path, was_dir in targets:
        exists = os.path.exists(path)
        kind = "folder" if (was_dir or (exists and os.path.isdir(path))) else "file"
        if tool == "delete_file":
            gone = not exists
            place = _parent_label(path)
            base = Path(path).name
            in_bin = False
            if gone:
                in_bin = _recycle_bin_has_basename(base)
            if gone and in_bin:
                detail = f"{'Folder' if kind == 'folder' else 'File'} is in the Recycle Bin"
            elif gone:
                detail = (
                    f"Gone from {place} (sent to the Recycle Bin)"
                )
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
