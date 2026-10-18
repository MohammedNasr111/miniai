"""Per-app trust for read-only desktop observation (Stage 8a).

Trusted apps live under %LOCALAPPDATA%\\MiniAI\\trusted_apps.json (a
protected path). Session grants and refusals clear on reset_session().
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BLOCKED_EXECUTABLES = frozenset(
    {
        "keepass.exe",
        "keepassxc.exe",
        "1password.exe",
        "bitwarden.exe",
        "lastpass.exe",
        "securityhealthui.exe",
        "systemsettings.exe",
        "consent.exe",
        "credentialuibroker.exe",
        "mmc.exe",
        "regedit.exe",
        "taskmgr.exe",
    }
)

_PASSWORD_MANAGER_TITLE = "password manager"

_session_allowed: set[str] = set()
_session_refused: set[str] = set()


class AppReadRefused(Exception):
    """User refused (or previously refused) reading this app this session."""


def clear_session() -> None:
    """Drop this-session grants and refusals (called from gate.reset_session)."""
    _session_allowed.clear()
    _session_refused.clear()


def trusted_apps_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "MiniAI"
    else:
        root = Path.home() / "AppData" / "Local" / "MiniAI"
    return root / "trusted_apps.json"


def normalize_exe(exe: str) -> str:
    return Path(str(exe)).name.lower()


def is_blocked(exe: str, title: str = "") -> bool:
    """True if this executable or window title must never be listed or read."""
    if normalize_exe(exe) in BLOCKED_EXECUTABLES:
        return True
    if _PASSWORD_MANAGER_TITLE in (title or "").lower():
        return True
    return False


def _load_trusted() -> dict:
    path = trusted_apps_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {normalize_exe(k): bool(v) for k, v in data.items() if v}


def _save_trusted(exe: str) -> None:
    path = trusted_apps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_trusted()
    data[normalize_exe(exe)] = True
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def is_trusted(exe: str) -> bool:
    key = normalize_exe(exe)
    if key in _session_allowed:
        return True
    return bool(_load_trusted().get(key))


def ensure_app_allowed(exe: str, title: str) -> None:
    """Allow reading this app, prompt the user, or refuse.

    Blocked apps raise ValueError. A refusal raises AppReadRefused and is
    remembered for the rest of the session (no re-prompt for that exe).
    """
    from security.gate import prompt_app_read

    key = normalize_exe(exe)
    safe_title = title or ""
    if is_blocked(key, safe_title):
        raise ValueError("MiniAI does not read this app.")
    if key in _session_refused:
        raise AppReadRefused(
            f"Reading {key} was refused earlier this session."
        )
    if is_trusted(key):
        return
    answer = prompt_app_read(key, safe_title)
    if answer == "session":
        _session_allowed.add(key)
        return
    if answer == "always":
        _save_trusted(key)
        _session_allowed.add(key)
        return
    _session_refused.add(key)
    raise AppReadRefused(f"Reading {key} was refused.")
