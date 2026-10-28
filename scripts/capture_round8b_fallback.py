"""Round 8b: capture visible cloud-fallback header (forced provider error)."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "app" / "design"
os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_r8b_"))
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
    from scripts.miniai_capture import capture_miniai_window

    return capture_miniai_window(path)



def _js(win, code: str):
    try:
        return win.evaluate_js(code)
    except Exception as exc:
        return {"err": str(exc)}


def main() -> int:
    import webview

    from app.webview_approver import AppBridge
    from llm.gemini.provider import GeminiQuotaError

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

        # Enable experimental cloud so Cloud button works, then force Gemini fail.
        _js(
            win,
            """
            (function(){
              try {
                localStorage.setItem('miniai.cloudExperimental', '1');
              } catch(e) {}
              var t = document.getElementById('cloud-experimental-toggle');
              if (t) { t.checked = true; t.dispatchEvent(new Event('change')); }
              return true;
            })()
            """,
        )
        time.sleep(0.4)

        from llm.gemini import provider as gem_mod

        class BoomGemini:
            def __init__(self, *a, **k):
                raise GeminiQuotaError(
                    "Gemini's free limit is used up for now. Answering on this PC instead."
                )

        # Patch before sending so the turn hits visible fallback.
        with patch.object(gem_mod, "GeminiProvider", BoomGemini):
            try:
                bridge.prepare_next_cloud(True)
                bridge.send_message("Say hello briefly.", cloud=True)
            except Exception as exc:
                print("SEND_ERR", type(exc).__name__, str(exc)[:160])

            # Wait for fallback text in the DOM (local Lemonade still answers).
            deadline = time.time() + 180
            found = False
            body = ""
            text = ""
            while time.time() < deadline:
                body = _js(
                    win,
                    "(document.body && document.body.innerText) || ''",
                )
                text = body if isinstance(body, str) else str(body)
                if "Gemini wasn't used" in text or "Answered on this PC" in text:
                    found = True
                    break
                time.sleep(1.0)

        path = OUT / "actual_r8b_cloud_fallback.png"
        _capture(path)
        (OUT / "actual_r8b_cloud_fallback.txt").write_text(
            text if isinstance(body, str) else str(body), encoding="utf-8"
        )
        print("SCENE_FALLBACK", "PASS" if found else "FAIL", "found=", found)
        time.sleep(0.3)
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
