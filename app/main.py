"""Launch the MiniAI app window (pywebview + Edge WebView2, no HTTP port)."""

from __future__ import annotations

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
INDEX = UI_DIR / "index.html"


def main() -> int:
    import webview

    from app.webview_approver import AppBridge
    from security.approver import set_approver

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    bridge = AppBridge()
    set_approver(bridge.approver)

    window = webview.create_window(
        title="MiniAI",
        url=INDEX.as_uri(),
        js_api=bridge.js_api,
        width=1100,
        height=720,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    bridge.window = window

    # Dark title bar on Windows when supported (pywebview 5 / Edge).
    try:
        webview.start(debug=False, private_mode=True)
    except TypeError:
        webview.start(debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
