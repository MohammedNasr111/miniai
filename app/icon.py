"""MiniAI window / process icon helpers (Windows)."""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

APP_USER_MODEL_ID = "MiniAI.Desktop"
_ASSETS = Path(__file__).resolve().parent / "assets"
ICO_PATH = _ASSETS / "miniai.ico"
LOGO_PATH = _ASSETS / "miniai_logo.png"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Call before any window is created so the process groups under MiniAI."""
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
        hr = shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        ok = int(hr) == 0
        if not ok:
            logger.warning("SetCurrentProcessExplicitAppUserModelID hr=%s", hr)
        return ok
    except Exception as exc:
        logger.warning("AppUserModelID failed: %s", exc)
        return False


def ico_path() -> Path:
    if ICO_PATH.is_file():
        return ICO_PATH
    fallback = Path(__file__).resolve().parent / "design" / "miniai.ico"
    return fallback if fallback.is_file() else ICO_PATH


def _load_icon(path: Path, cx: int, cy: int) -> int:
    user32 = ctypes.windll.user32
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010
    return int(
        user32.LoadImageW(
            None,
            str(path),
            IMAGE_ICON,
            int(cx),
            int(cy),
            LR_LOADFROMFILE,
        )
        or 0
    )


def apply_window_icon(window: Any, path: Optional[Path] = None) -> bool:
    """Set title-bar icons: Form.Icon plus WM_SETICON SMALL (16) and BIG (32)."""
    icon_file = Path(path) if path else ico_path()
    if not icon_file.is_file():
        logger.warning("icon file missing: %s", icon_file)
        return False
    ok = False
    # Prefer pywebview native Form.Icon when available.
    try:
        native = getattr(window, "native", None)
        form = None
        if native is not None:
            form = getattr(native, "form", None) or getattr(native, "window", None) or native
        if form is not None and hasattr(form, "Icon"):
            try:
                import clr  # type: ignore  # noqa: F401
                from System.Drawing import Icon as WinIcon  # type: ignore

                form.Icon = WinIcon(str(icon_file))
                logger.info("set form.Icon from %s", icon_file)
                ok = True
            except Exception as exc:
                logger.info("WinForms Icon set failed: %s", exc)
    except Exception as exc:
        logger.info("native form icon path failed: %s", exc)

    # Always also set WM_SETICON for both sizes (title bar often uses SMALL).
    try:
        from app.dark_titlebar import _hwnd_for

        hwnd = _hwnd_for(window)
        if not hwnd:
            return ok
        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        h_small = _load_icon(icon_file, 16, 16)
        h_big = _load_icon(icon_file, 32, 32)
        if not h_small and not h_big:
            # Fall back to default-size extract
            h_big = _load_icon(icon_file, 0, 0)
            h_small = h_big
        if h_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
            ok = True
        if h_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
            ok = True
        logger.info("WM_SETICON small/big applied for %s", icon_file)
        return ok
    except Exception as exc:
        logger.warning("WM_SETICON failed: %s", exc)
        return ok
