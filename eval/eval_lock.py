"""Round 13 Part 3 — eval.lock so nightly self-check skips while evals run."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

STALE_AFTER_S = 6 * 3600  # 6 hours


def eval_lock_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or ""
    if not local:
        # Fall back to real LocalAppData when env is missing (unusual).
        try:
            from config.paths import real_local_appdata

            local = str(real_local_appdata())
        except Exception:
            local = str(Path.home() / "AppData" / "Local")
    return Path(local) / "MiniAI" / "eval.lock"


def acquire_eval_lock(*, pid: Optional[int] = None) -> Path:
    """Write eval.lock with pid + start time. Overwrites stale locks."""
    path = eval_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": int(pid if pid is not None else os.getpid()),
        "started": time.time(),
        "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def release_eval_lock() -> None:
    path = eval_lock_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def read_eval_lock() -> Optional[dict[str, Any]]:
    path = eval_lock_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_error": "unreadable", "path": str(path)}
    return data if isinstance(data, dict) else None


def eval_lock_is_live(*, now: Optional[float] = None) -> tuple[bool, str]:
    """True when a non-stale eval.lock exists.

    Stale = missing started, or older than 6 h. Stale locks are removed.
    """
    data = read_eval_lock()
    if data is None:
        return False, "absent"
    if data.get("_error"):
        release_eval_lock()
        return False, "unreadable_cleared"
    try:
        started = float(data.get("started"))
    except (TypeError, ValueError):
        release_eval_lock()
        return False, "bad_started_cleared"
    t = time.time() if now is None else float(now)
    age = t - started
    if age > STALE_AFTER_S:
        release_eval_lock()
        return False, "stale_cleared"
    if age < -60:
        # Clock skew: treat as live but young.
        return True, "live_clock_skew"
    return True, f"live pid={data.get('pid')} age_s={int(age)}"
