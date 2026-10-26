"""Named mutex so only one MiniAI.Desktop process owns the UI."""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

MUTEX_NAME = "MiniAI.Desktop"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
SW_SHOW = 5

_mutex_handle: Optional[int] = None


def _bring_existing_to_front(title: str = "MiniAI") -> bool:
    """Find a top-level window titled MiniAI and restore / foreground it."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        # Fallback: any window whose title starts with MiniAI
        found = ctypes.c_void_p()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _enum(h, _lparam):  # type: ignore[misc]
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            if (buf.value or "") == title or (buf.value or "").startswith("MiniAI"):
                found.value = h
                return False
            return True

        user32.EnumWindows(_enum, 0)
        hwnd = found.value
    if not hwnd:
        logger.warning("second instance: mutex held but no MiniAI window found")
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    else:
        user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetForegroundWindow(hwnd)
    return True


def acquire_single_instance() -> bool:
    """Return True if this process should continue (owns the mutex).

    If another MiniAI is already running, bring it to the front and return False.
    """
    global _mutex_handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        logger.warning("CreateMutexW failed; continuing without single-instance lock")
        return True
    err = kernel32.GetLastError()
    if err == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        _bring_existing_to_front()
        return False
    _mutex_handle = int(handle)
    return True


def release_single_instance() -> None:
    global _mutex_handle
    if sys.platform != "win32" or not _mutex_handle:
        return
    try:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)  # type: ignore[attr-defined]
    except Exception:
        pass
    _mutex_handle = None
