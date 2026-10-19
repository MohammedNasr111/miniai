"""Live 11a check: mitochondria question + create_file via in-app approval cards."""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()


def main() -> int:
    import webview

    from app.webview_approver import AppBridge
    from security.approver import set_approver
    from security.gate import reset_session

    out_dir = Path(tempfile.mkdtemp(prefix="miniai_live_app_"))
    target = out_dir / "mito_note.txt"
    prompt = (
        "What molecule do mitochondria produce? Use web tools if needed. "
        f"Then create a file at {target} containing one short sentence "
        "with that answer."
    )
    print(f"PROMPT={prompt}")
    print(f"TARGET={target}")

    bridge = AppBridge()
    set_approver(bridge.approver)
    reset_session()

    def _kick():
        time.sleep(2.5)
        bridge.send_message(prompt)
        deadline = time.time() + 600
        while time.time() < deadline:
            if target.is_file():
                body = target.read_text(encoding="utf-8", errors="replace")
                print(f"CREATED={body!r}")
                time.sleep(1)
                if webview.windows:
                    webview.windows[0].destroy()
                return
            time.sleep(1)
        print("TIMEOUT waiting for create_file")
        if webview.windows:
            webview.windows[0].destroy()

    index = (PROJECT_ROOT / "app" / "ui" / "index.html").as_uri()
    win = webview.create_window(
        "MiniAI",
        index,
        js_api=bridge.js_api,
        width=1100,
        height=720,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    bridge.window = win

    def _on_loaded():
        try:
            win.evaluate_js("window.__MINIAI_AUTO_APPROVE=true")
            print("AUTO_APPROVE_FLAG_SET")
        except Exception as exc:
            print(f"AUTO_APPROVE_FLAG_ERR={exc}")

    win.events.loaded += _on_loaded
    threading.Thread(target=_kick, daemon=True).start()
    webview.start()
    ok = target.is_file()
    print(f"LIVE_OK={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
