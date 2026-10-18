"""Resolve and validate paths inside the isolated code workspace."""

from __future__ import annotations

import os
from pathlib import Path

from tools.code.paths import ensure_workspace, workspace_dir


class WorkspacePathError(ValueError):
    """Raised when a path is outside the workspace or otherwise refused."""


def resolve_in_workspace(path: str, *, must_exist: bool = False) -> Path:
    """Resolve path relative to the workspace; refuse anything outside it."""
    ws = ensure_workspace().resolve()
    raw = Path(path)
    if raw.is_absolute():
        target = raw
    else:
        target = ws / raw
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise WorkspacePathError(f"Cannot resolve path: {path} ({exc})") from exc

    ws_s = os.path.normcase(str(ws))
    t_s = os.path.normcase(str(resolved))
    if not (t_s == ws_s or t_s.startswith(ws_s + os.sep)):
        raise WorkspacePathError(
            f"Refused: path is outside the MiniAI workspace ({ws}): {path}"
        )
    if must_exist and not resolved.exists():
        raise WorkspacePathError(f"No such path in workspace: {path}")
    return resolved


def projects_dir() -> Path:
    d = ensure_workspace() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def numbered_text(text: str) -> str:
    lines = text.splitlines() or [""]
    width = max(2, len(str(len(lines))))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, 1))
