"""Native WebView2 navigation lock (cancel before navigate).

Attribute path used on Windows / pywebview 5.4 EdgeChromium:

  window.native                         -> BrowserView.BrowserForm
  window.native.browser                 -> EdgeChrome
  window.native.browser.webview         -> Microsoft.Web.WebView2.WinForms.WebView2
  window.native.browser.webview.NavigationStarting
  window.native.browser.webview.CoreWebView2.NewWindowRequested

(``window.native.webview`` is the same WebView2 instance.)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from pathlib import Path

logger = logging.getLogger(__name__)

# Shared cancel log for tests / diagnostics: list of (uri, reason)
_cancel_log: list[tuple[str, str]] = []
_lock = threading.Lock()


def clear_cancel_log() -> None:
    with _lock:
        _cancel_log.clear()


def get_cancel_log() -> list[tuple[str, str]]:
    with _lock:
        return list(_cancel_log)


def _note(uri: str, reason: str) -> None:
    with _lock:
        _cancel_log.append((uri, reason))
    logger.warning("NavigationStarting cancel: %s (%s)", uri, reason)


def path_from_url(url: str) -> Optional[Path]:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "file":
            return None
        path = url2pathname(unquote(parsed.path))
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path).resolve()
    except Exception:
        return None


def is_app_index_url(url: str, index_path: Path) -> bool:
    """True only when URL is the app index file (not about:blank)."""
    if not url:
        return False
    path = path_from_url(url)
    if path is None:
        return False
    try:
        return path == index_path.resolve()
    except Exception:
        return False


def is_boot_or_index(url: str, index_path: Path) -> bool:
    if not url or url in ("about:blank", "about:srcdoc"):
        return True
    return is_app_index_url(url, index_path)


def _uri_of(args: Any) -> str:
    try:
        if hasattr(args, "get_Uri"):
            return str(args.get_Uri())
    except Exception:
        pass
    try:
        return str(args.Uri)
    except Exception:
        return ""


def _set_cancel(args: Any) -> None:
    try:
        args.Cancel = True
        return
    except Exception:
        pass
    try:
        args.set_Cancel(True)
    except Exception as exc:
        logger.warning("could not set Cancel: %s", exc)


def _set_handled(args: Any) -> None:
    try:
        args.set_Handled(True)
        return
    except Exception:
        pass
    try:
        args.Handled = True
    except Exception as exc:
        logger.warning("could not set Handled: %s", exc)


def attach_native_nav_lock(
    window: Any,
    index_path: Path,
    open_external: Callable[[str], Any],
) -> bool:
    """Hook NavigationStarting + NewWindowRequested. Returns True if attached."""
    try:
        if getattr(window, "_miniai_nav_lock", False):
            return True
        form = getattr(window, "native", None)
        if form is None:
            logger.warning("nav_lock: window.native missing")
            return False
        edge = getattr(form, "browser", None)
        wv = getattr(edge, "webview", None) if edge is not None else None
        if wv is None:
            wv = getattr(form, "webview", None)
        if wv is None:
            logger.warning("nav_lock: WebView2 control missing")
            return False

        def on_navigation_starting(sender: Any, args: Any) -> None:
            uri = _uri_of(args)
            if is_boot_or_index(uri, index_path):
                return
            _set_cancel(args)
            _note(uri, "NavigationStarting")

        wv.NavigationStarting += on_navigation_starting

        def _attach_new_window() -> None:
            try:
                core = wv.CoreWebView2
            except Exception:
                core = None
            if core is None:
                return

            def on_new_window(sender: Any, args: Any) -> None:
                uri = _uri_of(args)
                _set_handled(args)
                if uri.lower().startswith("http://") or uri.lower().startswith(
                    "https://"
                ):
                    try:
                        open_external(uri)
                    except Exception as exc:
                        logger.warning("NewWindowRequested open_external: %s", exc)
                else:
                    _note(uri, "NewWindowRequested-refused")

            try:
                core.NewWindowRequested += on_new_window
            except Exception as exc:
                logger.warning("nav_lock: NewWindowRequested attach failed: %s", exc)

        # CoreWebView2 may already exist, or appear after init.
        try:
            if wv.CoreWebView2 is not None:
                _attach_new_window()
            else:
                def _on_ready(sender: Any, args: Any) -> None:
                    _attach_new_window()

                wv.CoreWebView2InitializationCompleted += _on_ready
        except Exception:
            _attach_new_window()

        window._miniai_nav_lock = True
        logger.info(
            "nav_lock attached via window.native.browser.webview "
            "(NavigationStarting + CoreWebView2.NewWindowRequested)"
        )
        return True
    except Exception as exc:
        logger.exception("nav_lock attach failed: %s", exc)
        return False
