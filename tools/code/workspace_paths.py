"""Resolve and validate paths inside the isolated code workspace."""

from __future__ import annotations

import os
from pathlib import Path

from tools.code.paths import ensure_workspace, workspace_dir

# Win32 FILE_ATTRIBUTE_REPARSE_POINT
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class WorkspacePathError(ValueError):
    """Raised when a path is outside the workspace or otherwise refused."""


def is_reparse_point(path: Path) -> bool:
    """True if path is a junction, symlink, or other reparse point (lstat)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", None)
    if attrs is not None and (attrs & _FILE_ATTRIBUTE_REPARSE_POINT):
        return True
    try:
        return bool(path.is_symlink())
    except OSError:
        return False


def assert_no_reparse_components(ws: Path, logical: Path) -> None:
    """Refuse if any existing path component from ws toward logical is a reparse point."""
    try:
        logical_abs = logical if logical.is_absolute() else (ws / logical)
        # Normalize without resolving reparse points: walk parts.
        parts = list(Path(os.path.abspath(str(logical_abs))).parts)
    except OSError as exc:
        raise WorkspacePathError(f"Cannot inspect path: {logical} ({exc})") from exc

    acc = Path(parts[0])
    for part in parts[1:]:
        acc = acc / part
        try:
            if is_reparse_point(acc):
                raise WorkspacePathError(
                    f"Refused: path crosses a junction or symlink "
                    f"(reparse point): {acc}"
                )
        except WorkspacePathError:
            raise
        except OSError:
            # Component does not exist yet — OK (e.g. creating a new file).
            break


def resolve_in_workspace(path: str, *, must_exist: bool = False) -> Path:
    """Resolve path relative to the workspace; refuse outside paths and junctions."""
    ws = ensure_workspace().resolve()
    raw = Path(path)
    if raw.is_absolute():
        target = raw
    else:
        target = ws / raw

    # Refuse before resolve follows a junction out of the workspace.
    assert_no_reparse_components(ws, target)

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
    # After resolve, also refuse if the resolved path itself is somehow a reparse
    # (defensive) or if any remaining link target escaped (already checked).
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
