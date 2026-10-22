"""Paths MiniAI must never modify with create/write/delete tools.

Refuse targets inside the project folder, browser_profile, or
%LOCALAPPDATA%\\MiniAI. Paths are fully resolved (absolute, symlinks and
``..`` removed) and compared case-insensitively.
"""

from __future__ import annotations

import os
from pathlib import Path

PROTECTED_MESSAGE = "MiniAI does not modify its own files or settings."

# security/ is one level below the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Explicit single-file protections (also covered by PROJECT_ROOT; listed so
# playbook stays protected even if root rules change). List only — no gate logic.
EXTRA_PROTECTED_FILES: tuple[Path, ...] = (
    PROJECT_ROOT / "prompts" / "playbook.md",
)


class ProtectedPathError(ValueError):
    """Raised when a mutating tool targets a protected path."""


def _miniai_data_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "MiniAI"
    return Path.home() / "AppData" / "Local" / "MiniAI"


def protected_roots() -> list[Path]:
    """Fully resolved roots that must not be modified."""
    roots = [
        PROJECT_ROOT.resolve(),
        (PROJECT_ROOT / "browser_profile").resolve(),
        _miniai_data_root().resolve(),
    ]
    # Deduplicate while preserving order (browser_profile is under PROJECT_ROOT).
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = os.path.normcase(str(root))
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def resolve_target(path: str | Path) -> Path:
    """Absolute path with symlinks and ``..`` removed."""
    return Path(path).expanduser().resolve()


def is_protected_path(path: str | Path) -> bool:
    """True if path is inside a protected root (case-insensitive)."""
    try:
        resolved = resolve_target(path)
    except OSError:
        # Unresolvable paths are still checked via absolute+normpath best-effort.
        resolved = Path(os.path.abspath(os.path.expanduser(str(path))))
    target = os.path.normcase(str(resolved))
    for extra in EXTRA_PROTECTED_FILES:
        try:
            extra_s = os.path.normcase(str(extra.resolve()))
        except OSError:
            extra_s = os.path.normcase(str(extra))
        if target == extra_s:
            return True
    for root in protected_roots():
        root_s = os.path.normcase(str(root))
        if target == root_s or target.startswith(root_s + os.sep):
            return True
    return False


def assert_not_protected(path: str | Path) -> Path:
    """Resolve path and raise ProtectedPathError if it is protected."""
    resolved = resolve_target(path)
    if is_protected_path(resolved):
        raise ProtectedPathError(PROTECTED_MESSAGE)
    return resolved
