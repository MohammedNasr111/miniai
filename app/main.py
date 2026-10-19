"""Launch the MiniAI app window (pywebview + Edge WebView2, no HTTP port)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

UI_DIR = Path(__file__).resolve().parent / "ui"
INDEX = UI_DIR / "index.html"

logger = logging.getLogger(__name__)


def index_uri() -> str:
    return INDEX.resolve().as_uri()


def _path_from_url(url: str) -> Path | None:
    try:
        parsed = urlparse(url)
        if parsed.scheme == "file":
            path = url2pathname(unquote(parsed.path))
            # On Windows url2pathname may yield /C:/...
            if path.startswith("/") and len(path) > 2 and path[2] == ":":
                path = path[1:]
            return Path(path).resolve()
        return None
    except Exception:
        return None


def _is_allowed_url(url: str) -> bool:
    if not url:
        return False
    # Allow about:blank during early boot; anything else must be our index.
    if url in ("about:blank", "about:srcdoc"):
        return True
    path = _path_from_url(url)
    if path is None:
        return False
    try:
        return path == INDEX.resolve()
    except Exception:
        return False


def main() -> int:
    import webview

    from app.dark_titlebar import apply_dark_titlebar
    from app.webview_approver import AppBridge
    from security.approver import set_approver

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    # Only our JS open_external path may open browsers.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False

    bridge = AppBridge()
    set_approver(bridge.approver)
    allowed = index_uri()

    window = webview.create_window(
        title="MiniAI",
        url=allowed,
        js_api=bridge.js_api,
        width=1100,
        height=720,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    bridge.window = window

    def _on_loaded() -> None:
        try:
            current = window.get_current_url() or ""
        except Exception:
            current = ""
        if not _is_allowed_url(current):
            logger.warning(
                "navigation lock: blocked URL %r — reloading index", current
            )
            try:
                window.load_url(allowed)
            except Exception as exc:
                logger.warning("navigation lock reload failed: %s", exc)
        apply_dark_titlebar(window)

    window.events.loaded += _on_loaded

    def _on_shown() -> None:
        apply_dark_titlebar(window)
        bridge.start_status_loop()

    try:
        window.events.shown += _on_shown
    except Exception:
        pass

    def _after_start() -> None:
        apply_dark_titlebar(window)
        bridge.start_status_loop()

    try:
        webview.start(func=_after_start, debug=False, private_mode=True)
    except TypeError:
        webview.start(func=_after_start, debug=False)
    bridge.stop_status_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
