"""Round 8: settings panel (key field empty) screenshot."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "app" / "design"
os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_r8_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

import ctypes
from ctypes import wintypes


def _set_size(w: int, h: int) -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if hwnd:
        user32.SetWindowPos(hwnd, 0, 40, 40, int(w), int(h), 0x0004)
        time.sleep(0.35)


def _capture(path: Path) -> bool:
    from PIL import ImageGrab

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if not hwnd:
        print("CAPTURE_ERR=no hwnd", path.name)
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    box = (rect.left, rect.top, rect.right, rect.bottom)
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.25)
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
    except TypeError:
        img = ImageGrab.grab(bbox=box)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    print(f"SAVED={path} size={img.size} md5={digest}")
    return True


def _js(win, code: str):
    try:
        return win.evaluate_js(code)
    except Exception as exc:
        return {"err": str(exc)}


def main() -> int:
    import webview

    from app.webview_approver import AppBridge

    bridge = AppBridge()
    ready = threading.Event()

    def _boot():
        ready.set()

    win = webview.create_window(
        "MiniAI",
        url=str(PROJECT_ROOT / "app" / "ui" / "index.html"),
        js_api=bridge.js_api,
        width=1100,
        height=720,
    )
    bridge.window = win

    def _work():
        if not ready.wait(30):
            print("FAIL ready timeout")
            win.destroy()
            return
        time.sleep(1.5)
        _set_size(1100, 720)
        # Open Cloud brain settings; ensure key input is empty.
        st = _js(
            win,
            """
            (function(){
              var p = document.getElementById('settings-panel');
              var inp = document.getElementById('gemini-key-input');
              if (p) p.hidden = false;
              if (inp) { inp.value = ''; }
              var status = document.getElementById('gemini-status-line');
              return {
                open: p && !p.hidden,
                keyEmpty: inp ? (inp.value === '') : false,
                keyType: inp ? inp.type : null,
                status: status ? status.textContent : null,
                text: (document.body.innerText||'').slice(0,800)
              };
            })()
            """,
        )
        print("ASSERT", st)
        ok = isinstance(st, dict) and st.get("open") and st.get("keyEmpty") and st.get("keyType") == "password"
        path = OUT / "actual_r8_cloud_settings.png"
        _capture(path)
        (OUT / "actual_r8_cloud_settings.txt").write_text(
            str(st.get("text") if isinstance(st, dict) else st), encoding="utf-8"
        )
        print("SCENE_SETTINGS", "PASS" if ok else "FAIL")
        # Cloud run header/footprint: SKIPPED without live Gemini key
        print("SCENE_CLOUD_RUN SKIPPED (no MINIAI_TEST_GEMINI_KEY)")
        time.sleep(0.4)
        try:
            win.destroy()
        except Exception:
            pass

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    webview.start(func=_boot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
