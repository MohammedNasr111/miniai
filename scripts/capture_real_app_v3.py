"""Launch the real MiniAI app, ask a live question, save actual_v3_*.png."""

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
# Isolated chat folder so the sidebar only shows this real conversation.
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v3_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT_RUNNING = PROJECT_ROOT / "app" / "design" / "actual_v3_running.png"
OUT_DONE = PROJECT_ROOT / "app" / "design" / "actual_v3_done.png"
PROMPT = (
    "What's the latest stable version of Python? "
    "You must use web_research. Cite your source."
)


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


def _probe(js: str):
    import webview

    try:
        return webview.windows[0].evaluate_js(js)
    except Exception as exc:
        return {"err": str(exc)}


def main() -> int:
    import webview

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from app.dark_titlebar import apply_dark_titlebar
    from app.main import INDEX, index_uri
    from app.nav_lock import attach_native_nav_lock
    from app.webview_approver import AppBridge
    from security.approver import set_approver
    from security.gate import reset_session

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    bridge = AppBridge()
    set_approver(bridge.approver)
    reset_session()

    state = {"running_shot": False, "done_shot": False, "probe": None}

    def _worker() -> None:
        time.sleep(2.8)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        win.evaluate_js("window.__MINIAI_AUTO_APPROVE=true")
        bridge.push_status()
        time.sleep(0.8)
        # Drive the real UI Send path so the user bubble appears.
        win.evaluate_js(
            f"""
            (function(){{
              const c = document.getElementById('composer');
              c.value = {PROMPT!r};
              document.getElementById('btn-send').click();
            }})();
            """
        )

        deadline = time.time() + 600
        while time.time() < deadline:
            probe = _probe(
                """
                (function(){
                  const sum = document.querySelector('.activity summary');
                  const steps = Array.from(document.querySelectorAll('.step'))
                    .map(el => el.textContent.trim());
                  const src = document.querySelectorAll('.source').length;
                  const mem = (document.getElementById('mem-label')||{}).textContent||'';
                  const model = (document.getElementById('model-status')||{}).textContent||'';
                  const hint = !!(document.querySelector('.hint'));
                  const spinner = !!document.querySelector('.spinner');
                  const user = !!document.querySelector('.msg-user');
                  const t = sum ? sum.textContent : '';
                  return {
                    summary: t.slice(0, 100),
                    steps: steps,
                    sources: src,
                    mem: mem,
                    model: model,
                    hint: hint,
                    spinner: spinner,
                    user: user,
                    worked: t.indexOf('Worked for') >= 0
                  };
                })();
                """
            )
            try:
                print(f"PROBE={probe!r}".encode("ascii", "replace").decode("ascii"))
            except Exception:
                print("PROBE=(unprintable)")
            # Prefer a frame that already shows a live tool step + spinner.
            if (
                isinstance(probe, dict)
                and not state["running_shot"]
                and probe.get("spinner")
                and probe.get("user")
                and any("Research" in s for s in (probe.get("steps") or []))
            ):
                time.sleep(0.35)
                state["running_shot"] = _capture_window(OUT_RUNNING)
            elif (
                isinstance(probe, dict)
                and not state["running_shot"]
                and probe.get("spinner")
                and probe.get("user")
                and time.time() > deadline - 480  # fallback after ~2 min
            ):
                state["running_shot"] = _capture_window(OUT_RUNNING)

            if (
                isinstance(probe, dict)
                and probe.get("worked")
                and not probe.get("spinner")
                and (probe.get("sources") or 0) >= 1
                and "Qwen3-30B-A3B" in (probe.get("model") or "")
                and "/" in (probe.get("mem") or "")
                and probe.get("hint")
            ):
                time.sleep(0.7)
                state["done_shot"] = _capture_window(OUT_DONE)
                state["probe"] = {
                    k: (str(v).encode("ascii", "replace").decode("ascii") if isinstance(v, str) else v)
                    for k, v in probe.items()
                }
                time.sleep(0.4)
                win.destroy()
                return
            time.sleep(1.2)
        print("TIMEOUT")
        _capture_window(OUT_DONE)
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
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.start_status_loop()

    win.events.loaded += _on_loaded
    threading.Thread(target=_worker, daemon=True).start()
    webview.start()
    print(
        f"RUNNING_OK={OUT_RUNNING.is_file()} DONE_OK={OUT_DONE.is_file()} "
        f"meta={state} chats={_chats}"
    )
    ok = (
        OUT_RUNNING.is_file()
        and OUT_DONE.is_file()
        and state.get("running_shot")
        and state.get("done_shot")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
