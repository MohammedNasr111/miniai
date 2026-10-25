"""Round 7 Part 7: capture actual_v9_*.png against the real MiniAI window."""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v9_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT = PROJECT_ROOT / "app" / "design"
SCENES_JS = (PROJECT_ROOT / "scripts" / "_v9_scenes.js").read_text(encoding="utf-8")


def _set_hwnd_size(w: int, h: int) -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if not hwnd:
        return
    # SWP_NOMOVE | SWP_NOZORDER
    user32.SetWindowPos(hwnd, 0, 0, 0, int(w), int(h), 0x0002 | 0x0004)
    time.sleep(0.35)


def _capture_window(path: Path) -> bool:
    from PIL import ImageGrab

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if not hwnd:
        print("CAPTURE_ERR=window not found", path.name)
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    box = (rect.left, rect.top, rect.right, rect.bottom)
    if box[2] <= box[0] or box[3] <= box[1]:
        return False
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.2)
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
    except TypeError:
        img = ImageGrab.grab(bbox=box)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print(f"SAVED={path} size={img.size} box={box}")
    return True


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
    state: dict[str, bool] = {}

    def _scene(win, name: str) -> str:
        # Escape for embedding
        js = SCENES_JS + f"; window.__v9Scene({name!r});"
        try:
            return win.evaluate_js(js) or ""
        except Exception as exc:
            print(f"scene {name} err: {exc}")
            return ""

    def _worker() -> None:
        time.sleep(3.2)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.push_status()
        _set_hwnd_size(1280, 860)
        time.sleep(0.6)

        shots = [
            ("empty", "actual_v9_empty.png"),
            ("ticket", "actual_v9_ticket_pending.png"),
            ("approved", "actual_v9_ticket_done.png"),
            ("web", "actual_v9_web_stream.png"),
            ("foot", "actual_v9_footprint.png"),
            ("palette", "actual_v9_palette.png"),
        ]
        for scene, fname in shots:
            got = _scene(win, scene)
            print(f"SCENE={scene} got={got!r}")
            time.sleep(0.45)
            state[scene] = _capture_window(OUT / fname)

        # Narrow 700
        _set_hwnd_size(720, 860)
        time.sleep(0.5)
        got = _scene(win, "narrow")
        print(f"SCENE=narrow got={got!r}")
        time.sleep(0.4)
        state["narrow"] = _capture_window(OUT / "actual_v9_narrow700.png")

        # Live turn (best effort)
        try:
            _set_hwnd_size(1280, 860)
            time.sleep(0.4)
            _scene(win, "empty")
            win.evaluate_js(
                """
                (function(){
                  const c = document.getElementById('composer');
                  c.value = 'Say hi in one short sentence.';
                  document.getElementById('composer-form').dispatchEvent(
                    new Event('submit', {cancelable:true, bubbles:true}));
                })();
                """
            )
            deadline = time.time() + 90
            while time.time() < deadline:
                probe = win.evaluate_js(
                    """
                    (function(){
                      return {
                        run: !!document.querySelector('.run .ask'),
                        stop: !!(document.getElementById('btn-send')||{}).classList.contains('is-stop'),
                        ticket: !!document.querySelector('.ticket'),
                        stream: !!document.querySelector('.stream-raw, .answer-md')
                      };
                    })();
                    """
                )
                print(f"LIVE={probe!r}")
                if isinstance(probe, dict) and (probe.get("stop") or probe.get("stream")):
                    time.sleep(0.5)
                    state["live"] = _capture_window(OUT / "actual_v9_live_run.png")
                    break
                time.sleep(0.6)
        except Exception as exc:
            print(f"live skipped: {exc}")

        try:
            win.destroy()
        except Exception:
            pass

    win = webview.create_window(
        "MiniAI",
        index_uri(),
        js_api=bridge.js_api,
        width=1280,
        height=860,
        min_size=(640, 500),
        background_color="#121821",
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
    required = ("empty", "ticket", "approved", "web", "foot", "palette", "narrow")
    ok = all(state.get(k) for k in required)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
