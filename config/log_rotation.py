"""Rotate MiniAI logs: agent logs ≤14 days or ≤2 GB (whichever is smaller).

Never delete ``review_*`` or ``eval_*.json`` from the last 30 days.
Safe to call at app start and after eval runs.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"

AGENT_MAX_AGE_S = 14 * 24 * 3600
AGENT_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
PROTECTED_MAX_AGE_S = 30 * 24 * 3600


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def rotate_logs(logs_dir: Path | None = None) -> dict[str, Any]:
    """Delete old agent logs under the age/size budget; protect recent reviews/evals.

    Strategy for agent_*:
      1. Never delete files newer than 14 days.
      2. Among older candidates, delete oldest-first until total agent_* size
         is ≤ 2 GB (also delete oldest among the keep-set if still over 2 GB).
    review_* and eval_*.json younger than 30 days are never deleted.
    Older review/eval files may be removed only when they exceed 30 days
    (not counted toward the 2 GB agent budget).
    """
    root = logs_dir or LOGS_DIR
    now = time.time()
    removed: list[str] = []
    kept_agent = 0
    freed = 0
    if not root.is_dir():
        return {"removed": 0, "freed_bytes": 0, "kept_agent": 0}

    # Protect recent review_* / eval_*.json
    protected: set[Path] = set()
    for pat in ("review_*", "eval_*.json"):
        for p in root.glob(pat):
            if not p.is_file():
                continue
            age = now - _mtime(p)
            if age <= PROTECTED_MAX_AGE_S:
                protected.add(p.resolve())
            else:
                # Older than 30 days: eligible for cleanup (not agent budget).
                try:
                    sz = _size(p)
                    p.unlink()
                    removed.append(p.name)
                    freed += sz
                except OSError as exc:
                    logger.info("log_rotation skip %s: %s", p.name, exc)

    agents = sorted(
        [p for p in root.glob("agent_*") if p.is_file()],
        key=lambda p: _mtime(p),  # oldest first
    )
    # First drop agent logs older than 14 days.
    remaining: list[Path] = []
    for p in agents:
        if p.resolve() in protected:
            remaining.append(p)
            continue
        age = now - _mtime(p)
        if age > AGENT_MAX_AGE_S:
            try:
                sz = _size(p)
                p.unlink()
                removed.append(p.name)
                freed += sz
            except OSError as exc:
                logger.info("log_rotation skip %s: %s", p.name, exc)
        else:
            remaining.append(p)

    # Enforce 2 GB cap on remaining agent logs (delete oldest first).
    total = sum(_size(p) for p in remaining)
    for p in remaining:
        if total <= AGENT_MAX_BYTES:
            break
        if p.resolve() in protected:
            continue
        try:
            sz = _size(p)
            p.unlink()
            removed.append(p.name)
            freed += sz
            total -= sz
        except OSError as exc:
            logger.info("log_rotation skip %s: %s", p.name, exc)

    kept_agent = len([p for p in root.glob("agent_*") if p.is_file()])
    result = {
        "removed": len(removed),
        "freed_bytes": freed,
        "kept_agent": kept_agent,
        "names": removed[:50],
    }
    logger.info(
        "log_rotation removed=%s freed_bytes=%s kept_agent=%s",
        result["removed"],
        result["freed_bytes"],
        result["kept_agent"],
    )
    return result


def read_selfcheck_summary(logs_dir: Path | None = None) -> dict[str, Any]:
    """Read logs/selfcheck_latest.json for the sidebar footer."""
    root = logs_dir or LOGS_DIR
    path = root / "selfcheck_latest.json"
    if not path.is_file():
        return {
            "ok": False,
            "label": "not run yet",
            "level": "ok",
            "passed": 0,
            "total": 0,
            "failed": 0,
        }
    try:
        import json

        # Nightly PowerShell may write UTF-8 with BOM.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {
            "ok": False,
            "label": "unreadable",
            "level": "danger",
            "error": str(exc),
            "passed": 0,
            "total": 0,
            "failed": 0,
        }
    if not isinstance(data, dict):
        return {
            "ok": False,
            "label": "unreadable",
            "level": "danger",
            "error": "not an object",
            "passed": 0,
            "total": 0,
            "failed": 0,
        }
    try:
        passed = int(data.get("passed") or 0)
        total = int(data.get("total") or 0)
        failed = int(data.get("failed") or max(0, total - passed))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "label": "unreadable",
            "level": "danger",
            "error": "bad counts",
            "passed": 0,
            "total": 0,
            "failed": 0,
        }
    date = data.get("date") or data.get("finished") or ""
    if isinstance(date, str) and len(date) >= 10:
        date = date[:10]
    # No middle-dot separators in UI strings (Round 7+).
    if failed == 0 and total > 0:
        label = f"{passed} of {total}"
        if date:
            label = f"{label}, {date}"
        return {
            "ok": True,
            "passed": passed,
            "total": total,
            "failed": 0,
            "date": date,
            "label": label,
            "level": "ok",
        }
    if total <= 0:
        return {
            "ok": False,
            "label": "not run yet",
            "level": "ok",
            "passed": 0,
            "total": 0,
            "failed": 0,
            "date": date,
        }
    label = f"{failed} failed"
    if date:
        label = f"{label}, {date}"
    return {
        "ok": False,
        "passed": passed,
        "total": total,
        "failed": failed,
        "date": date,
        "label": label,
        "level": "danger",
    }
