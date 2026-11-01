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
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from send2trash import send2trash

from security.gate import Tier, check_permission
from security.protected_paths import (
    PROTECTED_MESSAGE,
    ProtectedPathError,
    assert_not_protected,
)

# Appended when create_folder/create_file hit a protected path so the model
# recovers with workspace tools instead of retrying the same call (Round 9D).
_PROTECTED_CODING_HINT = (
    " Do not retry create_folder/create_file under the MiniAI project directory. "
    "For coding tasks, use ws_write to put files in the isolated workspace instead."
)

_FOLDER_WORD = re.compile(r"(?i)\bfolders?\b")

# Win32 GetDriveTypeW: only fixed local volumes are safe for Recycle Bin.
DRIVE_FIXED = 3
MAX_RECYCLE_BYTES = 500 * 1024 * 1024
READ_FILE_TEXT_CAP = 40_000
BINARY_PROBE_BYTES = 8192

def format_local_mtime(ts: float) -> str:
    """Human local mtime for list_directory answers, e.g. '28 Oct, 11:04 pm'."""
    try:
        dt = datetime.fromtimestamp(float(ts)).astimezone()
    except (OverflowError, OSError, ValueError, TypeError):
        return ""
    hour_12 = dt.strftime("%I").lstrip("0") or "12"
    ampm = dt.strftime("%p").lower()
    return f"{dt.day} {dt.strftime('%b')}, {hour_12}:{dt.strftime('%M')} {ampm}"


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

    root = resolve_fs_path(path)
    entries: list[dict[str, Any]] = []
    for name in os.listdir(root):
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
        mtime = float(st.st_mtime)
        modified = format_local_mtime(mtime)
        entries.append(
            {
                "name": name,
                "type": entry_type,
                "size_bytes": size_bytes,
                "size": size_h,
                "modified": modified,
                "_mtime": mtime,
            }
        )

    def _sort_val(e: dict[str, Any]):
        if sort_key == "size":
            # Dirs sort as -1 so they group; files by bytes.
            return e["size_bytes"] if e["size_bytes"] is not None else -1
        if sort_key == "modified":
            return float(e.get("_mtime") or 0.0)
        return (e.get("name") or "").lower()

    entries.sort(key=_sort_val, reverse=bool(descending))
    if len(entries) > lim:
        entries = entries[:lim]
    for e in entries:
        e.pop("_mtime", None)
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
    """Accept normal paths and file:// URIs; expand Desktop/~/Desktop to real folders."""
    from config.paths import expand_user_path

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
    return expand_user_path(raw)


def resolve_create_path(path: str) -> Path:
    """Resolve paths for create_folder / create_file / write_file.

    Round 12 Part 6: bare relative paths (e.g. ``Inbox`` or ``notes.txt``) land
    on the user's Desktop — never the MiniAI repo cwd. Absolute paths and
    ``Desktop\\…`` / ``Documents\\…`` expansions are unchanged. Eval override
    (11B) still remaps Desktop into the temp tree.
    """
    from config.paths import resolve_user_folders

    target = resolve_fs_path(path)
    if not target.is_absolute():
        desktop = resolve_user_folders()["Desktop"]
        target = desktop.joinpath(*target.parts) if target.parts else desktop
    return target


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


def _under_existing_user_folder(target: Path) -> bool:
    """True if target is under a resolved Desktop/Documents/… that exists."""
    from config.paths import resolve_user_folders

    try:
        resolved = target if target.is_absolute() else target.resolve()
    except OSError:
        resolved = target
    for root in resolve_user_folders().values():
        try:
            root_res = root.resolve()
        except OSError:
            root_res = root
        if not root_res.is_dir():
            continue
        try:
            resolved.resolve().relative_to(root_res)
            return True
        except (ValueError, OSError):
            try:
                # Compare without requiring target to exist yet
                pref = str(root_res).rstrip("\\/").lower()
                cand = str(resolved).rstrip("\\/").lower()
                if cand == pref or cand.startswith(pref + "\\") or cand.startswith(pref + "/"):
                    return True
            except Exception:
                continue
    return False


def create_folder(path: str) -> str:
    """Create a new directory. CONFIRM; refuses if it already exists."""
    target = resolve_create_path(path)
    shown = str(target)
    try:
        assert_not_protected(shown)
    except ProtectedPathError:
        raise ProtectedPathError(PROTECTED_MESSAGE + _PROTECTED_CODING_HINT) from None
    if target.exists():
        raise FileExistsError(
            f"Path already exists, not creating folder: {shown}."
        )
    parent = target.parent
    if not parent.exists():
        if not _under_existing_user_folder(target):
            raise FileNotFoundError(
                f"Parent folder does not exist: {parent}. "
                "Create folders only inside an existing user folder "
                "(Desktop, Documents, Downloads, …)."
            )
        # Parents allowed only under an existing known user folder.
    check_permission(
        action="create_folder",
        tier=Tier.CONFIRM,
        description=f"Create new folder: {shown}",
    )
    if target.exists():
        raise FileExistsError(
            f"Path already exists, not creating folder: {shown}."
        )
    target.mkdir(parents=True, exist_ok=False)
    try:
        from agent.action_claim_check import note_fs_verify_target

        note_fs_verify_target("create_folder", shown, was_dir=True)
    except Exception:
        pass
    return f"Created folder {shown}."


def create_file(path: str, content: str) -> str:
    from tools.filesystem.turn_context import get_turn_user_text

    target = resolve_create_path(path)
    shown = str(target)
    try:
        assert_not_protected(shown)
    except ProtectedPathError:
        raise ProtectedPathError(PROTECTED_MESSAGE + _PROTECTED_CODING_HINT) from None
    # Folder requests must not create extensionless files named like folders.
    user_q = get_turn_user_text()
    if (
        _FOLDER_WORD.search(user_q)
        and not target.suffix
        and not str(path).rstrip().endswith(("/", "\\"))
    ):
        raise ValueError(
            f"Refusing create_file for {shown!r}: the user asked for a folder "
            "and this path has no file extension. Call create_folder instead."
        )
    check_permission(
        action="create_file",
        tier=Tier.CONFIRM,
        description=f"Create new file: {shown}\n---\n{content}\n---",
    )
    if target.exists():
        raise FileExistsError(
            f"File already exists, not overwriting: {shown}. "
            "Use write_file if you intend to replace its contents."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    try:
        from agent.action_claim_check import note_fs_verify_target

        note_fs_verify_target("create_file", shown, was_dir=False)
    except Exception:
        pass
    _commit_if_workspace(shown, f"create_file {shown}")
    return f"Created {shown} ({len(content.encode('utf-8'))} bytes written)."


def write_file(path: str, content: str) -> str:
    target = resolve_create_path(path)
    shown = str(target)
    assert_not_protected(shown)
    if target.exists():
        description = (
            f"Overwrite existing file: {shown}\n"
            f"A backup of the current file will be kept.\n"
            f"---\n{content}\n---"
        )
    else:
        description = f"Create file (did not exist): {shown}\n---\n{content}\n---"
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
                f"Backup failed before overwrite of {shown}; nothing was written. "
                f"({exc})"
            ) from exc
        target.write_text(content, encoding="utf-8")
        _commit_if_workspace(shown, f"write_file {shown}")
        try:
            from agent.action_claim_check import note_fs_verify_target

            note_fs_verify_target("write_file", shown, was_dir=False)
        except Exception:
            pass
        return (
            f"Overwrote {shown} ({len(content.encode('utf-8'))} bytes written). "
            f"Backup saved at {backup_path}."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _commit_if_workspace(shown, f"write_file {shown}")
    try:
        from agent.action_claim_check import note_fs_verify_target

        note_fs_verify_target("write_file", shown, was_dir=False)
    except Exception:
        pass
    return f"Overwrote {shown} ({len(content.encode('utf-8'))} bytes written)."


def delete_file(path: str) -> str:
    target = resolve_fs_path(path)
    shown = str(target)
    assert_not_protected(shown)
    if not target.exists():
        raise FileNotFoundError(f"No such file or folder: {shown}")
    is_dir = target.is_dir()
    kind = "folder" if is_dir else "file"
    # Drive type and size checks before any permission prompt.
    assert_safe_for_recycle_bin(target)
    check_permission(
        action="delete_file",
        tier=Tier.ALWAYS_CONFIRM,
        description=(
            f"Move folder to Recycle Bin: {shown}"
            if is_dir
            else f"Move to Recycle Bin: {shown}"
        ),
    )
    try:
        send2trash(str(target.resolve()))
    except Exception as exc:
        # Never fall back to a permanent delete.
        raise RuntimeError(
            f"Could not move {shown} to the Recycle Bin ({exc}). "
            f"The {kind} was left in place."
        ) from exc
    try:
        from agent.action_claim_check import note_fs_verify_target

        note_fs_verify_target("delete_file", shown, was_dir=is_dir)
    except Exception:
        pass
    _commit_if_workspace(shown, f"delete_file {shown}")
    return (
        f"Moved {kind} {shown} to the Recycle Bin. It can be restored from there."
    )


def move_file(src: str, dest: str) -> str:
    """Move or rename a file. Creates the destination parent directory if needed.

    Refuses protected paths. Does not overwrite an existing destination.
    Prompts at CONFIRM before acting.
    Prefer move_files when organising many files (one confirmation).
    """
    source = resolve_fs_path(src)
    destination = resolve_fs_path(dest)
    src_s, dest_s = str(source), str(destination)
    assert_not_protected(src_s)
    assert_not_protected(dest_s)
    if not source.exists():
        raise FileNotFoundError(f"No such file: {src_s}")
    if not source.is_file():
        raise IsADirectoryError(
            f"move_file only moves files, not directories: {src_s}"
        )
    if destination.exists():
        raise FileExistsError(
            f"Destination already exists, not overwriting: {dest_s}"
        )
    check_permission(
        action="move_file",
        tier=Tier.CONFIRM,
        description=f"Move file:\n  from: {src_s}\n  to:   {dest_s}",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    _commit_if_workspace(src_s, f"move_file {src_s} -> {dest_s}")
    _commit_if_workspace(dest_s, f"move_file {src_s} -> {dest_s}")
    return f"Moved {src_s} to {dest_s}."


MAX_BATCH_MOVES = 200
_BATCH_LIST_DISPLAY = 30


def _validate_one_move(src: str, dest: str) -> tuple[str, str, Path, Path]:
    """Same protections as move_file; raises before any permission prompt."""
    source = resolve_fs_path(src)
    destination = resolve_fs_path(dest)
    src_s, dest_s = str(source), str(destination)
    assert_not_protected(src_s)
    assert_not_protected(dest_s)
    if not source.exists():
        raise FileNotFoundError(f"No such file: {src_s}")
    if not source.is_file():
        raise IsADirectoryError(
            f"move_files only moves files, not directories: {src_s}"
        )
    if destination.exists():
        raise FileExistsError(
            f"Destination already exists, not overwriting: {dest_s}"
        )
    return src_s, dest_s, source, destination


def move_files(moves: list[dict[str, str]]) -> str:
    """Move many files with a single CONFIRM prompt.

    Prefer this over repeated move_file when organising a folder by type.
    Each item is {\"src\": ..., \"dest\": ...}. Max 200 moves. All moves are
    validated before asking; a later failure does not undo earlier successes.
    """
    if not isinstance(moves, list) or not moves:
        raise ValueError("moves must be a non-empty list of {src, dest} objects.")
    if len(moves) > MAX_BATCH_MOVES:
        raise ValueError(
            f"Too many moves ({len(moves)}); max is {MAX_BATCH_MOVES}."
        )

    planned: list[tuple[str, str, Path, Path]] = []
    for i, item in enumerate(moves):
        if not isinstance(item, dict):
            raise ValueError(f"moves[{i}] must be an object with src and dest.")
        src = item.get("src")
        dest = item.get("dest")
        if not isinstance(src, str) or not isinstance(dest, str) or not src or not dest:
            raise ValueError(
                f"moves[{i}] requires non-empty string src and dest."
            )
        planned.append(_validate_one_move(src, dest))

    # Detect duplicate destinations in the batch (would overwrite mid-batch).
    seen_dest: set[str] = set()
    for src, dest, _s, _d in planned:
        key = os.path.normcase(os.path.abspath(dest))
        if key in seen_dest:
            raise FileExistsError(
                f"Duplicate destination in batch, not overwriting: {dest}"
            )
        seen_dest.add(key)

    lines = [f"Move {len(planned)} file(s):"]
    for src, dest, _s, _d in planned[:_BATCH_LIST_DISPLAY]:
        lines.append(f"  {src}  ->  {dest}")
    if len(planned) > _BATCH_LIST_DISPLAY:
        more = len(planned) - _BATCH_LIST_DISPLAY
        lines.append(f"  … and {more} more")
    check_permission(
        action="move_files",
        tier=Tier.CONFIRM,
        description="\n".join(lines),
    )

    ok_lines: list[str] = []
    err_lines: list[str] = []
    for src, dest, source, destination in planned:
        try:
            if destination.exists():
                raise FileExistsError(
                    f"Destination already exists, not overwriting: {dest}"
                )
            if not source.exists() or not source.is_file():
                raise FileNotFoundError(f"No such file: {src}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            _commit_if_workspace(src, f"move_files {src} -> {dest}")
            _commit_if_workspace(dest, f"move_files {src} -> {dest}")
            ok_lines.append(f"OK: {src} -> {dest}")
        except Exception as exc:
            err_lines.append(f"FAIL: {src} -> {dest} ({exc})")

    summary = [
        f"Batch move finished: {len(ok_lines)} succeeded, {len(err_lines)} failed "
        f"of {len(planned)}."
    ]
    summary.extend(ok_lines)
    summary.extend(err_lines)
    return "\n".join(summary)


def _commit_if_workspace(path: str, message: str) -> None:
    """Version the isolated code workspace after MiniAI mutates a path in it."""
    try:
        from tools.code.workspace_git import maybe_commit_workspace_path

        maybe_commit_workspace_path(path, message)
    except Exception:
        # Versioning must not undo a successful file operation.
        pass
