"""Independent filesystem checks after successful create/delete (not tool text)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def _paths_from_transcript(transcript: Any, tool_names: set[str]) -> list[tuple[str, str]]:
    """Return (tool, path) pairs from successful tool_call events."""
    if transcript is None:
        return []
    path = getattr(transcript, "path", None)
    if path is None:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "tool_call":
            continue
        name = str(ev.get("name") or "")
        if name not in tool_names:
            continue
        if str(ev.get("outcome") or "ok").lower() in ("denied", "failed", "error"):
            continue
        args = ev.get("args") or {}
        p = args.get("path")
        if isinstance(p, str) and p.strip():
            out.append((name, p.strip()))
    return out


def verify_create_delete(transcript: Any = None) -> dict[str, Any]:
    """os.path.exists checks for create_file / create_folder / delete_file.

    Returns a meta dict with ``checks`` (list of {tool, path, ok, detail})
    and ``passed`` / ``ran`` flags for UI + footprint.
    """
    pairs = _paths_from_transcript(
        transcript, {"create_file", "create_folder", "delete_file"}
    )
    checks: list[dict[str, Any]] = []
    for tool, path in pairs:
        exists = os.path.exists(path)
        if tool == "delete_file":
            ok = not exists
            detail = (
                "File is in the Recycle Bin"
                if ok
                else f"File still present on disk: {path}"
            )
        elif tool == "create_folder":
            ok = exists and os.path.isdir(path)
            detail = "Folder exists on disk" if ok else f"Folder missing: {path}"
        else:
            ok = exists and os.path.isfile(path)
            detail = "File exists on disk" if ok else f"File missing: {path}"
        checks.append(
            {
                "tool": tool,
                "path": path,
                "ok": ok,
                "detail": detail,
            }
        )
    passed = [c for c in checks if c["ok"]]
    return {
        "ran": bool(checks),
        "passed": bool(passed) and all(c["ok"] for c in checks),
        "checks": checks,
        "summary": "; ".join(c["detail"] for c in passed) if passed else "",
    }
