"""Persisted app preferences (%LOCALAPPDATA%\\MiniAI\\app.json)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


def prefs_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "MiniAI" / "app.json"


def load_prefs() -> dict[str, Any]:
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("prefs load failed: %s", exc)
        return {}


def save_prefs(data: dict[str, Any]) -> None:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def apply_prefs_to_settings() -> None:
    """Disk prefs no longer control CHECKER (toggle removed). Ignore app.json."""
    # Intentionally ignore prefs["checker"] / checker=true — env MINIAI_CHECKER
    # and settings.CHECKER (default off) are the only experiment knobs.
    return


def get_checker_pref() -> str:
    """Env-only (experiments). Saved app.json checker is ignored."""
    env = os.environ.get("MINIAI_CHECKER", "").strip().lower()
    if env in ("off", "on"):
        return env
    v = str(getattr(settings, "CHECKER", "off") or "off").lower()
    return v if v in ("off", "on") else "off"


def set_checker_pref(value: str) -> str:
    """In-process only for experiments; do not persist to app.json."""
    v = "on" if str(value).strip().lower() == "on" else "off"
    settings.CHECKER = v
    return v


def get_cloud_experimental() -> bool:
    """Whether Settings → Experimental: cloud brain is on (survives restart)."""
    return bool(load_prefs().get("cloud_experimental"))


def set_cloud_experimental(on: bool) -> bool:
    data = load_prefs()
    data["cloud_experimental"] = bool(on)
    save_prefs(data)
    return bool(on)


def get_gemini_quota_blocked_until() -> float | None:
    """Unix time when a recent free-tier quota hit was recorded (or None)."""
    raw = load_prefs().get("gemini_quota_hit_at")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def set_gemini_quota_hit_at(when: float | None) -> None:
    data = load_prefs()
    if when is None:
        data.pop("gemini_quota_hit_at", None)
    else:
        data["gemini_quota_hit_at"] = float(when)
    save_prefs(data)
