"""Groq API key at rest: Windows DPAPI (current user), never plaintext on disk.

Stored at ``%LOCALAPPDATA%\\MiniAI\\secrets\\groq.bin``. The key string is
never returned to the WebView after save — only ``connected`` / status.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATUS_CONNECTED = "Connected"
STATUS_NOT_CONNECTED = "Not connected"
STATUS_REJECTED = "Key rejected by Groq"
STATUS_TEST_OK = "Test OK"
STATUS_TEST_FAIL = "Test failed"


def secrets_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "MiniAI" / "secrets"
    else:
        root = Path.home() / "AppData" / "Local" / "MiniAI" / "secrets"
    return root


def key_path() -> Path:
    return secrets_dir() / "groq.bin"


def has_key() -> bool:
    try:
        return key_path().is_file() and key_path().stat().st_size > 0
    except OSError:
        return False


def _protect(plaintext: bytes) -> bytes:
    import win32crypt  # type: ignore

    blob = win32crypt.CryptProtectData(plaintext, "MiniAI Groq key", None, None, None, 0)
    return bytes(blob)


def _unprotect(blob: bytes) -> bytes:
    import win32crypt  # type: ignore

    _desc, data = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    return bytes(data)


def save_key(api_key: str) -> dict[str, Any]:
    """Encrypt and write the key. Returns UI-safe status (never echoes the key)."""
    raw = (api_key or "").strip()
    if not raw:
        return {"ok": False, "connected": False, "status": STATUS_NOT_CONNECTED, "error": "empty"}
    try:
        d = secrets_dir()
        d.mkdir(parents=True, exist_ok=True)
        blob = _protect(raw.encode("utf-8"))
        path = key_path()
        path.write_bytes(blob)
        try:
            import ctypes

            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)  # HIDDEN
        except Exception:
            pass
        return {"ok": True, "connected": True, "status": STATUS_CONNECTED}
    except Exception as exc:
        logger.warning("groq_key save failed: %s", type(exc).__name__)
        return {
            "ok": False,
            "connected": False,
            "status": STATUS_NOT_CONNECTED,
            "error": "save_failed",
        }


def load_key() -> Optional[str]:
    """Decrypt the key for server-side use only. Never pass to the WebView."""
    path = key_path()
    if not path.is_file():
        return None
    try:
        blob = path.read_bytes()
        if not blob:
            return None
        return _unprotect(blob).decode("utf-8")
    except Exception as exc:
        logger.warning("groq_key load failed: %s", type(exc).__name__)
        return None


def remove_key() -> dict[str, Any]:
    path = key_path()
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:
        logger.warning("groq_key remove failed: %s", type(exc).__name__)
        return {
            "ok": False,
            "connected": has_key(),
            "status": STATUS_CONNECTED if has_key() else STATUS_NOT_CONNECTED,
            "error": "remove_failed",
        }
    try:
        d = secrets_dir()
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    except OSError:
        pass
    return {"ok": True, "connected": False, "status": STATUS_NOT_CONNECTED}


def status(*, rejected: bool = False) -> dict[str, Any]:
    """UI-safe connection status. Never includes the key string."""
    if rejected:
        return {
            "ok": True,
            "connected": has_key(),
            "status": STATUS_REJECTED,
        }
    connected = has_key()
    return {
        "ok": True,
        "connected": connected,
        "status": STATUS_CONNECTED if connected else STATUS_NOT_CONNECTED,
    }


def mark_rejected() -> dict[str, Any]:
    flag = secrets_dir() / "groq.rejected"
    try:
        secrets_dir().mkdir(parents=True, exist_ok=True)
        flag.write_text("1", encoding="utf-8")
    except OSError:
        pass
    return status(rejected=True)


def clear_rejected() -> None:
    flag = secrets_dir() / "groq.rejected"
    try:
        if flag.is_file():
            flag.unlink()
    except OSError:
        pass


def ui_status() -> dict[str, Any]:
    if (secrets_dir() / "groq.rejected").is_file() and has_key():
        return status(rejected=True)
    return status()
