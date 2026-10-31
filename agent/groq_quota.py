"""Local Groq free-tier quota gate (RPM / RPD / TPM / TPD).

Counts stay on this PC. On deny or after a 429, callers fall back to the
local planner. Never logs API keys.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Documented free-tier-ish ceilings (Round 11).
RPM = 30
RPD = 1000
TPM = 8000
TPD = 200_000


def _state_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "MiniAI"
    else:
        root = Path.home() / "AppData" / "Local" / "MiniAI"
    return root / "groq_quota.json"


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"events": [], "blocked_until": 0.0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"events": [], "blocked_until": 0.0}
        data.setdefault("events", [])
        data.setdefault("blocked_until", 0.0)
        return data
    except (OSError, json.JSONDecodeError):
        return {"events": [], "blocked_until": 0.0}


def _save(data: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        logger.info("groq_quota save failed: %s", type(exc).__name__)


def _prune(events: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    cutoff = now - 86_400.0
    out: list[dict[str, Any]] = []
    for ev in events:
        try:
            t = float(ev.get("t", 0))
        except (TypeError, ValueError):
            continue
        if t >= cutoff:
            out.append({"t": t, "tokens": int(ev.get("tokens") or 0)})
    return out


def blocked_until() -> float:
    data = _load()
    try:
        return float(data.get("blocked_until") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def set_blocked_until(when: float) -> None:
    data = _load()
    data["blocked_until"] = float(when)
    data["events"] = _prune(list(data.get("events") or []), time.time())
    _save(data)


def note_retry_after(seconds: float | None, *, default: float = 60.0) -> float:
    """Block further Groq calls until now + retry-after (or default)."""
    try:
        wait = float(seconds) if seconds is not None else default
    except (TypeError, ValueError):
        wait = default
    wait = max(1.0, min(wait, 3600.0))
    until = time.time() + wait
    set_blocked_until(until)
    return until


def estimate_tokens(text: str) -> int:
    """Rough local estimate when the API does not return usage."""
    n = len(text or "")
    return max(1, (n + 3) // 4)


def check_allowed(*, estimated_tokens: int = 1) -> tuple[bool, str]:
    """Return (ok, reason). reason is empty when ok."""
    now = time.time()
    data = _load()
    try:
        until = float(data.get("blocked_until") or 0.0)
    except (TypeError, ValueError):
        until = 0.0
    if until > now:
        return False, f"retry-after until {until:.0f}"

    events = _prune(list(data.get("events") or []), now)
    data["events"] = events
    _save(data)

    minute = [e for e in events if float(e["t"]) >= now - 60.0]
    day = events
    rpm = len(minute)
    rpd = len(day)
    tpm = sum(int(e.get("tokens") or 0) for e in minute)
    tpd = sum(int(e.get("tokens") or 0) for e in day)
    need = max(1, int(estimated_tokens))

    if rpm >= RPM:
        return False, f"rpm {rpm}>={RPM}"
    if rpd >= RPD:
        return False, f"rpd {rpd}>={RPD}"
    if tpm + need > TPM:
        return False, f"tpm {tpm}+{need}>{TPM}"
    if tpd + need > TPD:
        return False, f"tpd {tpd}+{need}>{TPD}"
    return True, ""


def record_request(*, tokens: int) -> None:
    now = time.time()
    data = _load()
    events = _prune(list(data.get("events") or []), now)
    events.append({"t": now, "tokens": max(1, int(tokens))})
    data["events"] = events
    _save(data)


def snapshot() -> dict[str, Any]:
    now = time.time()
    data = _load()
    events = _prune(list(data.get("events") or []), now)
    minute = [e for e in events if float(e["t"]) >= now - 60.0]
    return {
        "rpm": len(minute),
        "rpd": len(events),
        "tpm": sum(int(e.get("tokens") or 0) for e in minute),
        "tpd": sum(int(e.get("tokens") or 0) for e in events),
        "limits": {"rpm": RPM, "rpd": RPD, "tpm": TPM, "tpd": TPD},
        "blocked_until": float(data.get("blocked_until") or 0.0),
    }


def reset_for_tests() -> None:
    """Wipe counters (offline tests only)."""
    path = _state_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass
