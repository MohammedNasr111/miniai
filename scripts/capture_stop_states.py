"""Capture idle + running Stop button states from the real MiniAI app."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v4_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT_IDLE = PROJECT_ROOT / "app" / "design" / "actual_v4_idle.png"
OUT_RUNNING = PROJECT_ROOT / "app" / "design" / "actual_v4_running.png"


def _capture_window(path: Path) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if not hwnd:
        print("CAPTURE_ERR=window not found")
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return False
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    if not user32.PrintWindow(hwnd, mem, 2):
        desk = user32.GetDC(0)
        gdi32.BitBlt(mem, 0, 0, w, h, desk, rect.left, rect.top, 0x00CC0020)
        user32.ReleaseDC(0, desk)
    try:
        from PIL import Image

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        buf = (ctypes.c_char * (w * h * 4))()
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
        img = Image.frombuffer("RGB", (w, h), bytes(buf), "raw", "BGRX", 0, 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        print(f"SAVED={path} size={w}x{h}")
        return True
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def main() -> int:
    import webview

    from app.dark_titlebar import apply_dark_titlebar
    from app.main import INDEX, index_uri
    from app.nav_lock import attach_native_nav_lock
    from app.webview_approver import AppBridge
    from security.approver import set_approver
    from security.gate import reset_session

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    bridge = AppBridge()
    # Skip warm-up wait for a quick UI capture: mark model ready.
    bridge._model_loading = False
    bridge._model_ready.set()
    bridge._warmup_started = True
    set_approver(bridge.approver)
    reset_session()

    state = {"idle": False, "running": False}

    def _worker() -> None:
        time.sleep(2.5)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.push_status()
        time.sleep(0.6)
        # Idle: Stop disabled.
        probe = win.evaluate_js(
            """
            (function(){
              const s=document.getElementById('btn-stop');
              const send=document.getElementById('btn-send');
              return {
                stopDisabled: !!s.disabled,
                stopIdle: s.classList.contains('is-idle'),
                sendDisabled: !!send.disabled,
                title: s.getAttribute('title')
              };
            })();
            """
        )
        print(f"IDLE_PROBE={probe!r}")
        state["idle"] = _capture_window(OUT_IDLE)
        # Force running controls without a long LLM turn.
        win.evaluate_js(
            "window.miniai && window.miniai._set_turn_controls && "
            "window.miniai._set_turn_controls(true);"
            "window.miniai.on_activity({steps:[{name:'Working…',t:'',running:true}],"
            "waiting:false,total:'3s',running:true});"
        )
        time.sleep(0.5)
        probe2 = win.evaluate_js(
            """
            (function(){
              const s=document.getElementById('btn-stop');
              const send=document.getElementById('btn-send');
              return {
                stopDisabled: !!s.disabled,
                stopIdle: s.classList.contains('is-idle'),
                sendDisabled: !!send.disabled,
                title: s.getAttribute('title')
              };
            })();
            """
        )
        print(f"RUN_PROBE={probe2!r}")
        state["running"] = _capture_window(OUT_RUNNING)
        time.sleep(0.3)
        try:
            win.destroy()
        except Exception:
            pass

    win = webview.create_window(
        "MiniAI",
        index_uri(),
        js_api=bridge.js_api,
        width=1100,
        height=720,
        min_size=(900, 600),
        background_color="#0D0E11",
    )
    bridge.window = win

    def _on_loaded() -> None:
        apply_dark_titlebar(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        # Status loop without starting a real warm-up again.
        bridge.push_status()

    win.events.loaded += _on_loaded
    threading.Thread(target=_worker, daemon=True).start()
    webview.start()
    ok = (
        OUT_IDLE.is_file()
        and OUT_RUNNING.is_file()
        and state["idle"]
        and state["running"]
    )
    print(f"OK={ok} idle={OUT_IDLE} running={OUT_RUNNING}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
