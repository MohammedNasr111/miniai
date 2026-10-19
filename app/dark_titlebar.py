"""Enable Windows immersive dark mode on the pywebview HWND."""

from __future__ import annotations

import ctypes
import logging
from typing import Any

logger = logging.getLogger(__name__)

# DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win10 20H1+); 19 on older builds.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19


def apply_dark_titlebar(window: Any) -> bool:
    """Set dark title bar via DwmSetWindowAttribute. Returns True on success."""
    try:
        hwnd = _hwnd_for(window)
        if not hwnd:
            return False
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1)
        for attr in (
            _DWMWA_USE_IMMERSIVE_DARK_MODE,
            _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD,
        ):
            hr = dwmapi.DwmSetWindowAttribute(
                hwnd,
                attr,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if hr == 0:
                return True
        return False
    except Exception as exc:
        logger.info("dark title bar unavailable: %s", exc)
        return False


def _hwnd_for(window: Any) -> int:
    # pywebview WinForms / Edge: native_handle or gui window handle.
    for attr in ("native_window", "native", "hwnd"):
        h = getattr(window, attr, None)
        if h is not None:
            try:
                return int(h)
            except (TypeError, ValueError):
                pass
    try:
        import win32gui  # type: ignore

        return int(win32gui.FindWindow(None, "MiniAI"))
    except Exception:
        pass
    user32 = ctypes.windll.user32
    return int(user32.FindWindowW(None, "MiniAI") or 0)
