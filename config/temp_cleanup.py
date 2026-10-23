"""Delete stale MiniAI temp folders under %TEMP%\\miniai_* only."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
DEFAULT_MAX_AGE_S = 24 * 3600


def _is_reparse_point(path: Path) -> bool:
    """True for junctions/symlinks (reparse points) on Windows."""
    if os.name != "nt":
        return path.is_symlink()
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    except Exception:
        return path.is_symlink()
    if attrs == INVALID_FILE_ATTRIBUTES:
        return path.is_symlink()
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def _dir_size_bytes(root: Path) -> int:
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            # Do not descend through reparse points.
            keep: list[str] = []
            for name in list(dirnames):
                child = Path(dirpath) / name
                if _is_reparse_point(child):
                    continue
                keep.append(name)
            dirnames[:] = keep
            for name in filenames:
                fp = Path(dirpath) / name
                if _is_reparse_point(fp):
                    continue
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _rmtree_safe(root: Path) -> None:
    """Remove root; never recurse through junctions — rmdir them instead."""

    def _onexc(func, p, exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    # First pass: strip reparse points so rmtree cannot follow them.
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
            for name in dirnames + filenames:
                child = Path(dirpath) / name
                if _is_reparse_point(child):
                    try:
                        os.rmdir(child) if child.is_dir() else child.unlink()
                    except OSError:
                        try:
                            os.rmdir(child)
                        except OSError:
                            pass
    except OSError:
        pass
    if _is_reparse_point(root):
        try:
            os.rmdir(root)
        except OSError:
            pass
        return
    shutil.rmtree(root, onexc=_onexc)


def cleanup_stale_miniai_temps(
    *,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    temp_root: Optional[Path] = None,
) -> dict:
    """Delete %TEMP%\\miniai_* directories older than max_age_s.

    Never touches paths outside that prefix. Returns counts and bytes freed.
    """
    base = Path(temp_root) if temp_root is not None else Path(os.environ.get("TEMP") or tempfile_gettempdir())
    now = time.time()
    removed = 0
    freed = 0
    skipped = 0
    errors: list[str] = []
    try:
        entries = list(base.iterdir())
    except OSError as exc:
        return {
            "removed": 0,
            "freed_bytes": 0,
            "skipped": 0,
            "errors": [str(exc)],
            "temp_root": str(base),
        }
    for entry in entries:
        name = entry.name
        if not name.lower().startswith("miniai_"):
            continue
        if not entry.is_dir():
            continue
        # Must stay under temp root (no escape).
        try:
            resolved = entry.resolve()
            if base.resolve() not in resolved.parents and resolved != base.resolve():
                # resolve may point elsewhere via junction — only delete if the
                # path string itself is directly under base.
                if entry.parent.resolve() != base.resolve():
                    skipped += 1
                    continue
        except OSError:
            skipped += 1
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            skipped += 1
            continue
        if age < max_age_s:
            skipped += 1
            continue
        size = _dir_size_bytes(entry)
        try:
            _rmtree_safe(entry)
            if not entry.exists():
                removed += 1
                freed += size
            else:
                errors.append(f"still exists: {entry}")
        except Exception as exc:
            errors.append(f"{entry}: {exc}")
    result = {
        "removed": removed,
        "freed_bytes": freed,
        "skipped": skipped,
        "errors": errors,
        "temp_root": str(base),
    }
    logger.info(
        "temp cleanup: removed=%s freed_bytes=%s skipped=%s",
        removed,
        freed,
        skipped,
    )
    return result


def tempfile_gettempdir() -> str:
    import tempfile

    return tempfile.gettempdir()
