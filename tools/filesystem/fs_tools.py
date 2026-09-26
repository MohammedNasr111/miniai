"""Filesystem tools. Each function checks its permission tier before
acting - see security/gate.py for tiers.

The mutating tools return a descriptive success string rather than None:
the model reads the tool result to decide whether it is done, and a
bare None serialized to "null" reads as a non-answer, which made it
retry the same destructive call until the round cap.
"""

import os
from pathlib import Path

from security.gate import Tier, check_permission


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


def create_file(path: str, content: str) -> str:
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
    check_permission(
        action="write_file",
        tier=Tier.CONFIRM,
        description=f"Overwrite existing file: {path}\n---\n{content}\n---",
    )
    Path(path).write_text(content, encoding="utf-8")
    return f"Overwrote {path} ({len(content.encode('utf-8'))} bytes written)."


def delete_file(path: str) -> str:
    check_permission(
        action="delete_file",
        tier=Tier.ALWAYS_CONFIRM,
        description=f"PERMANENTLY DELETE: {path}",
    )
    os.remove(path)
    return f"Deleted {path}. This cannot be undone."
