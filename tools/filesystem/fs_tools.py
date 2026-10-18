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

import os
import shutil
from datetime import datetime
from pathlib import Path

from send2trash import send2trash

from security.gate import Tier, check_permission
from security.protected_paths import assert_not_protected


def list_directory(path: str) -> list[str]:
    check_permission(
        action="list_directory",
        tier=Tier.AUTO_ALLOW,
        description=f"List contents of: {path}",
    )
    return os.listdir(path)


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


def read_file(path: str) -> str:
    check_permission(
        action="read_file",
        tier=Tier.AUTO_ALLOW,
        description=f"Read file: {path}",
    )
    return Path(path).read_text(encoding="utf-8", errors="replace")


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
        description = f"Overwrite existing file: {path}\n---\n{content}\n---"
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
        return (
            f"Overwrote {path} ({len(content.encode('utf-8'))} bytes written). "
            f"Backup saved at {backup_path}."
        )
    target.write_text(content, encoding="utf-8")
    return f"Overwrote {path} ({len(content.encode('utf-8'))} bytes written)."


def delete_file(path: str) -> str:
    assert_not_protected(path)
    check_permission(
        action="delete_file",
        tier=Tier.ALWAYS_CONFIRM,
        description=f"Move to Recycle Bin: {path}",
    )
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"No such file: {path}")
    try:
        send2trash(str(target.resolve()))
    except Exception as exc:
        # Never fall back to a permanent delete.
        raise RuntimeError(
            f"Could not move {path} to the Recycle Bin ({exc}). "
            "The file was left in place."
        ) from exc
    return (
        f"Moved {path} to the Recycle Bin. It can be restored from there."
    )
