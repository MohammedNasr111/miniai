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
    """Load disk prefs into settings (env MINIAI_CHECKER still wins if set)."""
    if os.environ.get("MINIAI_CHECKER", "").strip():
        return
    prefs = load_prefs()
    checker = str(prefs.get("checker") or "off").strip().lower()
    if checker in ("off", "on"):
        settings.CHECKER = checker


def get_checker_pref() -> str:
    env = os.environ.get("MINIAI_CHECKER", "").strip().lower()
    if env in ("off", "on"):
        return env
    prefs = load_prefs()
    v = str(prefs.get("checker") or settings.CHECKER or "off").lower()
    return v if v in ("off", "on") else "off"


def set_checker_pref(value: str) -> str:
    v = "on" if str(value).strip().lower() == "on" else "off"
    settings.CHECKER = v
    # Env override: still update settings for this process, but only persist
    # when env is not forcing the value.
    if not os.environ.get("MINIAI_CHECKER", "").strip():
        prefs = load_prefs()
        prefs["checker"] = v
        save_prefs(prefs)
    return v
