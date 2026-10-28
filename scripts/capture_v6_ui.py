"""Capture actual_v6_titlebar / idle / running screenshots for QA Round 2 Part 5."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v6_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT = PROJECT_ROOT / "app" / "design"


def _capture_window(path: Path, crop_titlebar: bool = False) -> bool:
    from scripts.miniai_capture import capture_miniai_window

    ok = capture_miniai_window(path)
    if not ok:
        return False
    if crop_titlebar:
        from PIL import Image

        img = Image.open(path)
        w, h = img.size
        # Keep a titlebar strip for icon checks (still MiniAI HWND bits).
        img.crop((0, 0, w, min(40, h))).save(path)
    return True


def _probe(js: str):
    import webview

    try:
        return webview.windows[0].evaluate_js(js)
    except Exception as exc:
        return {"err": str(exc)}


def main() -> int:
    import webview

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from app.dark_titlebar import apply_dark_titlebar
    from app.icon import apply_window_icon
    from app.main import INDEX, index_uri
    from app.nav_lock import attach_native_nav_lock
    from app.webview_approver import AppBridge
    from security.approver import set_approver
    from security.gate import reset_session

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    bridge = AppBridge()
    set_approver(bridge.approver)
    reset_session()
    state = {"idle": False, "running": False, "title": False}

    def _worker() -> None:
        time.sleep(2.8)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        win.evaluate_js("window.__MINIAI_AUTO_APPROVE=true")
        bridge.push_status()
        time.sleep(0.8)
        state["idle"] = _capture_window(OUT / "actual_v6_idle.png")
        state["title"] = _capture_window(
            OUT / "actual_v6_titlebar.png", crop_titlebar=True
        )
        win.evaluate_js(
            """
            (function(){
              const c = document.getElementById('composer');
              c.value = 'Hi, what can you do?';
              document.getElementById('btn-send').click();
            })();
            """
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            probe = _probe(
                """
                (function(){
                  return {
                    user: !!document.querySelector('.msg-user'),
                    stop: !!(document.getElementById('btn-send')||{}).classList.contains('is-stop'),
                    spinner: !!document.querySelector('.spinner'),
                    userText: (document.querySelector('.msg-user')||{}).textContent||''
                  };
                })();
                """
            )
            print(f"PROBE={probe!r}")
            if (
                isinstance(probe, dict)
                and probe.get("user")
                and probe.get("stop")
                and not state["running"]
            ):
                time.sleep(0.35)
                state["running"] = _capture_window(OUT / "actual_v6_running.png")
                break
            time.sleep(0.8)
        time.sleep(0.5)
        try:
            win.destroy()
        except Exception:
            pass

    win = webview.create_window(
        "MiniAI",
        index_uri(),
        js_api=bridge.js_api,
        width=1360,
        height=860,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    bridge.window = win

    def _on_loaded() -> None:
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.start_status_loop()

    win.events.loaded += _on_loaded
    threading.Thread(target=_worker, daemon=True).start()
    webview.start()
    print(f"STATE={state}")
    ok = state["idle"] and state["running"] and state["title"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
