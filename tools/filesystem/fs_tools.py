"""Filesystem tools. Each function checks its permission tier before
acting - see security/gate.py for tiers.

Mutating tools never permanently destroy data: deletes go to the Recycle
Bin, and overwrites keep a timestamped backup under
%LOCALAPPDATA%\\MiniAI\\backups. Targets inside the agent folder or
MiniAI settings are refused before the permission prompt.

The mutating tools return a descriptive success string rather than None:
the model reads the tool result to decide whether it is done, and a
bare None serialized to "null" reads as a non-answer, which made it
retry the same destructive call until the round cap.
"""

from __future__ import annotations

import ctypes
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from send2trash import send2trash

from security.gate import Tier, check_permission
from security.protected_paths import assert_not_protected

# Win32 GetDriveTypeW: only fixed local volumes are safe for Recycle Bin.
DRIVE_FIXED = 3
MAX_RECYCLE_BYTES = 500 * 1024 * 1024
READ_FILE_TEXT_CAP = 40_000
BINARY_PROBE_BYTES = 8192

# Extension → short label for refuse messages. Special cases handled separately.
_BINARY_EXT_LABELS: dict[str, str] = {
    ".zip": "ZIP archive",
    ".7z": "7z archive",
    ".rar": "RAR archive",
    ".exe": "Windows executable",
    ".dll": "Windows library",
    ".msi": "Windows installer",
    ".iso": "disk image",
    ".img": "disk image",
    ".png": "PNG image",
    ".jpg": "JPEG image",
    ".jpeg": "JPEG image",
    ".gif": "GIF image",
    ".webp": "WebP image",
    ".mp3": "MP3 audio",
    ".mp4": "MP4 video",
    ".mov": "QuickTime video",
}
_OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}
_PDF_EXT = ".pdf"


class UnsafeDeleteError(ValueError):
    """Raised when delete_file refuses before the permission prompt."""


def _drive_root(path: Path) -> str:
    """Return a root like ``C:\\`` for GetDriveTypeW."""
    resolved = path.resolve()
    drive = resolved.drive
    if not drive:
        raise UnsafeDeleteError(
            "This file cannot be safely sent to the Recycle Bin "
            "(path has no drive letter). MiniAI will not delete it; "
            "delete it yourself if you mean to."
        )
    return drive + "\\"


def get_drive_type(path: Path) -> int:
    """ctypes.windll.kernel32.GetDriveTypeW for the path's drive."""
    return int(ctypes.windll.kernel32.GetDriveTypeW(_drive_root(path)))


def assert_safe_for_recycle_bin(path: Path) -> None:
    """Refuse deletes Windows would not send to the Recycle Bin.

    Only DRIVE_FIXED (3) volumes and files of at most 500 MB are allowed.
    Raises UnsafeDeleteError before any permission prompt.
    """
    drive_type = get_drive_type(path)
    if drive_type != DRIVE_FIXED:
        raise UnsafeDeleteError(
            "This file cannot be safely sent to the Recycle Bin "
            f"(not a fixed local drive; GetDriveTypeW={drive_type}). "
            "MiniAI will not delete it; delete it yourself if you mean to."
        )
    size = path.stat().st_size
    if size > MAX_RECYCLE_BYTES:
        raise UnsafeDeleteError(
            "This file cannot be safely sent to the Recycle Bin "
            f"(file larger than 500 MB; size={size} bytes). "
            "MiniAI will not delete it; delete it yourself if you mean to."
        )


def human_size(num_bytes: int) -> str:
    """Human-readable size, e.g. '640 KB' or '4.2 MB'."""
    n = float(max(0, int(num_bytes)))
    units = [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024), ("B", 1)]
    for label, scale in units:
        if n >= scale or label == "B":
            if label == "B":
                return f"{int(n)} B"
            val = n / scale
            if val >= 100 or abs(val - round(val)) < 0.05:
                return f"{int(round(val))} {label}"
            return f"{val:.1f} {label}"
    return f"{int(n)} B"


def list_directory(
    path: str,
    sort_by: str = "name",
    descending: Optional[bool] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List directory entries with name, type, size, and modified time.

    sort_by: "name" | "size" | "modified" (default name).
    descending: default False for name, True for size/modified (largest/newest first).
    limit: default 200, max 1000.
    """
    check_permission(
        action="list_directory",
        tier=Tier.AUTO_ALLOW,
        description=f"List contents of: {path}",
    )
    sort_key = (sort_by or "name").strip().lower()
    if sort_key not in ("name", "size", "modified"):
        sort_key = "name"
    if descending is None:
        descending = sort_key in ("size", "modified")
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        lim = 200
    lim = max(1, min(lim, 1000))

    root = Path(path)
    entries: list[dict[str, Any]] = []
    for name in os.listdir(path):
        full = root / name
        try:
            st = full.lstat()
        except OSError:
            continue
        if full.is_dir():
            entry_type = "dir"
            size_bytes: Optional[int] = None
            size_h: Optional[str] = None
        else:
            entry_type = "file"
            size_bytes = int(st.st_size)
            size_h = human_size(size_bytes)
        try:
            modified = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except (OverflowError, OSError, ValueError):
            modified = ""
        entries.append(
            {
                "name": name,
                "type": entry_type,
                "size_bytes": size_bytes,
                "size": size_h,
                "modified": modified,
            }
        )

    def _sort_val(e: dict[str, Any]):
        if sort_key == "size":
            # Dirs sort as -1 so they group; files by bytes.
            return e["size_bytes"] if e["size_bytes"] is not None else -1
        if sort_key == "modified":
            return e.get("modified") or ""
        return (e.get("name") or "").lower()

    entries.sort(key=_sort_val, reverse=bool(descending))
    if len(entries) > lim:
        entries = entries[:lim]
    return entries


def search_files(root: str, pattern: str) -> list[str]:
    check_permission(
        action="search_files",
        tier=Tier.AUTO_ALLOW,
        description=f"Search under {root} for pattern: {pattern}",
    )
    matches = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if pattern.lower() in name.lower():
                matches.append(os.path.join(dirpath, name))
    return matches


def _binary_refuse_message(path: Path, label: str, size_bytes: int) -> str:
    return (
        f"{path.name} is a binary file ({label}, {human_size(size_bytes)}); "
        "its size is in list_directory."
    )


def resolve_fs_path(path: str) -> Path:
    """Accept normal paths and file:// URIs (common when prompts pass a page URI)."""
    raw = (path or "").strip()
    if raw.lower().startswith("file:"):
        from urllib.parse import unquote, urlparse
        from urllib.request import url2pathname

        parsed = urlparse(raw)
        # Windows: file:///C:/Users/... → /C:/Users/... → C:\Users\...
        local = url2pathname(unquote(parsed.path or ""))
        if parsed.netloc and not local.startswith("\\\\"):
            # file://localhost/C:/... or file://server/share
            if parsed.netloc.lower() not in ("", "localhost"):
                local = "\\\\" + parsed.netloc + local
        raw = local
    return Path(raw)


def read_file(path: str) -> str:
    check_permission(
        action="read_file",
        tier=Tier.AUTO_ALLOW,
        description=f"Read file: {path}",
    )
    target = resolve_fs_path(path)
    if not target.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    try:
        size_bytes = int(target.stat().st_size)
    except OSError as exc:
        raise FileNotFoundError(f"Cannot stat file: {path}") from exc

    ext = target.suffix.lower()
    if ext == _PDF_EXT:
        return (
            f"{target.name} is a PDF ({human_size(size_bytes)}). "
            "Use the knowledge tool for PDFs; read_file cannot return PDF text."
        )
    if ext in _OFFICE_EXTS:
        kind = {".docx": "Word", ".xlsx": "Excel", ".pptx": "PowerPoint"}[ext]
        return (
            f"{target.name} is a {kind} document ({human_size(size_bytes)}); "
            "Office formats are not supported as text. "
            "Its size is in list_directory."
        )
    if ext in _BINARY_EXT_LABELS:
        return _binary_refuse_message(target, _BINARY_EXT_LABELS[ext], size_bytes)

    # NUL-byte probe (first 8 KB) catches unlabeled binaries.
    try:
        with target.open("rb") as fh:
            head = fh.read(BINARY_PROBE_BYTES)
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc
    if b"\x00" in head:
        return _binary_refuse_message(target, "binary", size_bytes)

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc
    if len(text) > READ_FILE_TEXT_CAP:
        shown = text[:READ_FILE_TEXT_CAP]
        text = (
            f"{shown}\n\n[truncated: showing first {READ_FILE_TEXT_CAP} of "
            f"{len(text)} chars]"
        )
    from tools.filesystem.untrusted_file import maybe_wrap_outside_file

    return maybe_wrap_outside_file(target, text)

def _backups_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError(
            "LOCALAPPDATA is not set; cannot create a backup before overwrite."
        )
    return Path(local) / "MiniAI" / "backups"


def backup_existing_file(target: Path) -> Path:
    """Copy target to %LOCALAPPDATA%\\MiniAI\\backups\\<stamp>_<name>."""
    backup_root = _backups_dir()
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_root / f"{stamp}_{target.name}"
    if dest.exists():
        # Same-second collision: add a numeric suffix.
        n = 1
        while True:
            candidate = backup_root / f"{stamp}_{n}_{target.name}"
            if not candidate.exists():
                dest = candidate
                break
            n += 1
    shutil.copy2(target, dest)
    return dest


def create_file(path: str, content: str) -> str:
    assert_not_protected(path)
    check_permission(
        action="create_file",
        tier=Tier.CONFIRM,
        description=f"Create new file: {path}\n---\n{content}\n---",
    )
    target = Path(path)
    if target.exists():
        raise FileExistsError(
            f"File already exists, not overwriting: {path}. "
            "Use write_file if you intend to replace its contents."
        )
    target.write_text(content, encoding="utf-8")
    _commit_if_workspace(path, f"create_file {path}")
    return f"Created {path} ({len(content.encode('utf-8'))} bytes written)."


def write_file(path: str, content: str) -> str:
    assert_not_protected(path)
    target = Path(path)
    if target.exists():
        description = (
            f"Overwrite existing file: {path}\n"
            f"A backup of the current file will be kept.\n"
            f"---\n{content}\n---"
        )
    else:
        description = f"Create file (did not exist): {path}\n---\n{content}\n---"
    check_permission(
        action="write_file",
        tier=Tier.CONFIRM,
        description=description,
    )
    if target.exists():
        try:
            backup_path = backup_existing_file(target)
        except Exception as exc:
            raise RuntimeError(
                f"Backup failed before overwrite of {path}; nothing was written. "
                f"({exc})"
            ) from exc
        target.write_text(content, encoding="utf-8")
        _commit_if_workspace(path, f"write_file {path}")
        return (
            f"Overwrote {path} ({len(content.encode('utf-8'))} bytes written). "
            f"Backup saved at {backup_path}."
        )
    target.write_text(content, encoding="utf-8")
    _commit_if_workspace(path, f"write_file {path}")
    return f"Overwrote {path} ({len(content.encode('utf-8'))} bytes written)."


def delete_file(path: str) -> str:
    assert_not_protected(path)
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"No such file: {path}")
    # Drive type and size checks before any permission prompt.
    assert_safe_for_recycle_bin(target)
    check_permission(
        action="delete_file",
        tier=Tier.ALWAYS_CONFIRM,
        description=f"Move to Recycle Bin: {path}",
    )
    try:
        send2trash(str(target.resolve()))
    except Exception as exc:
        # Never fall back to a permanent delete.
        raise RuntimeError(
            f"Could not move {path} to the Recycle Bin ({exc}). "
            "The file was left in place."
        ) from exc
    _commit_if_workspace(path, f"delete_file {path}")
    return (
        f"Moved {path} to the Recycle Bin. It can be restored from there."
    )


def move_file(src: str, dest: str) -> str:
    """Move or rename a file. Creates the destination parent directory if needed.

    Refuses protected paths. Does not overwrite an existing destination.
    Prompts at CONFIRM before acting.
    """
    assert_not_protected(src)
    assert_not_protected(dest)
    source = Path(src)
    destination = Path(dest)
    if not source.exists():
        raise FileNotFoundError(f"No such file: {src}")
    if not source.is_file():
        raise IsADirectoryError(
            f"move_file only moves files, not directories: {src}"
        )
    if destination.exists():
        raise FileExistsError(
            f"Destination already exists, not overwriting: {dest}"
        )
    check_permission(
        action="move_file",
        tier=Tier.CONFIRM,
        description=f"Move file:\n  from: {src}\n  to:   {dest}",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    _commit_if_workspace(src, f"move_file {src} -> {dest}")
    _commit_if_workspace(dest, f"move_file {src} -> {dest}")
    return f"Moved {src} to {dest}."


def _commit_if_workspace(path: str, message: str) -> None:
    """Version the isolated code workspace after MiniAI mutates a path in it."""
    try:
        from tools.code.workspace_git import maybe_commit_workspace_path

        maybe_commit_workspace_path(path, message)
    except Exception:
        # Versioning must not undo a successful file operation.
        pass
