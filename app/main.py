"""Launch the MiniAI app window (pywebview + Edge WebView2, no HTTP port)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
INDEX = UI_DIR / "index.html"

logger = logging.getLogger(__name__)


def index_uri() -> str:
    return INDEX.resolve().as_uri()


# Re-export helpers used by tests / bridge.
from app.nav_lock import (  # noqa: E402
    is_app_index_url,
    is_boot_or_index,
    path_from_url,
)


def _is_allowed_url(url: str) -> bool:
    """After-load layer: index or about:blank."""
    return is_boot_or_index(url, INDEX)


def main() -> int:
    import webview

    from app.dark_titlebar import apply_dark_titlebar
    from app.icon import apply_window_icon, ico_path, set_app_user_model_id
    from app.nav_lock import attach_native_nav_lock
    from app.webview_approver import AppBridge
    from config.temp_cleanup import cleanup_stale_miniai_temps
    from security.approver import set_approver

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    # Must run before any HWND / WinForms window is created.
    set_app_user_model_id()

    try:
        cleaned = cleanup_stale_miniai_temps()
        logger.info(
            "temp cleanup removed=%s freed_bytes=%s",
            cleaned.get("removed"),
            cleaned.get("freed_bytes"),
        )
    except Exception as exc:
        logger.warning("temp cleanup failed: %s", exc)

    # Only our JS / NewWindowRequested path may open browsers.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False

    from app.prefs import apply_prefs_to_settings

    apply_prefs_to_settings()

    bridge = AppBridge()
    set_approver(bridge.approver)
    allowed = index_uri()
    index_path = INDEX.resolve()

    icon = str(ico_path()) if ico_path().is_file() else None
    create_kwargs = dict(
        title="MiniAI",
        url=allowed,
        js_api=bridge.js_api,
        width=1100,
        height=720,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    if icon:
        try:
            window = webview.create_window(**create_kwargs, icon=icon)
        except TypeError:
            window = webview.create_window(**create_kwargs)
    else:
        window = webview.create_window(**create_kwargs)
    bridge.window = window

    def _on_loaded() -> None:
        try:
            current = window.get_current_url() or ""
        except Exception:
            current = ""
        if not is_boot_or_index(current, index_path):
            logger.warning(
                "navigation lock (after-load): blocked URL %r — reloading index",
                current,
            )
            try:
                window.load_url(allowed)
            except Exception as exc:
                logger.warning("navigation lock reload failed: %s", exc)
        apply_dark_titlebar(window)
        apply_window_icon(window)
        # Native hooks need window.native (set when the form exists).
        attach_native_nav_lock(window, index_path, bridge.open_external)

    window.events.loaded += _on_loaded

    def _on_shown() -> None:
        apply_dark_titlebar(window)
        apply_window_icon(window)
        attach_native_nav_lock(window, index_path, bridge.open_external)
        bridge.start_status_loop()

    try:
        window.events.shown += _on_shown
    except Exception:
        pass

    def _after_start() -> None:
        apply_dark_titlebar(window)
        apply_window_icon(window)
        attach_native_nav_lock(window, index_path, bridge.open_external)
        bridge.start_status_loop()

    try:
        webview.start(func=_after_start, debug=False, private_mode=True)
    except TypeError:
        webview.start(func=_after_start, debug=False)
    bridge.stop_status_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
