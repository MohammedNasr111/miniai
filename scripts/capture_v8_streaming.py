"""Capture mid-stream screenshot: app/design/actual_v8_streaming.png."""

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
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v8_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT = PROJECT_ROOT / "app" / "design" / "actual_v8_streaming.png"


def _capture_full(path: Path) -> bool:
    from scripts.miniai_capture import capture_miniai_window

    return capture_miniai_window(path)

PROBE_JS = """
(function(){
  const raw = document.querySelector('.stream-raw');
  const md = document.querySelector('.answer-md');
  const txt = raw ? (raw.textContent||'') : '';
  const btn = document.getElementById('btn-send');
  const act = document.querySelector('details.activity summary');
  const user = document.querySelector('.msg-user');
  return {
    hasStream: !!raw,
    streamLen: txt.length,
    streamPreview: txt.slice(0, 120),
    hasAnswer: !!md,
    answerLen: md ? (md.textContent||'').length : 0,
    isStop: !!(btn && btn.classList.contains('is-stop')),
    activity: act ? (act.textContent||'').slice(0, 80) : '',
    hasUser: !!user,
    userText: user ? (user.textContent||'').slice(0, 60) : ''
  };
})();
"""


def main() -> int:
    import logging

    import webview

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    from app.dark_titlebar import apply_dark_titlebar
    from app.icon import apply_window_icon
    from app.main import INDEX, index_uri
    from app.nav_lock import attach_native_nav_lock
    from app.webview_approver import AppBridge
    from security.approver import set_approver
    from security.gate import reset_session

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    bridge = AppBridge()
    bridge._model_loading = False
    bridge._model_ready.set()
    set_approver(bridge.approver)
    reset_session()

    result = {"ok": False, "probe": None, "note": ""}

    def _probe():
        try:
            return webview.windows[0].evaluate_js(PROBE_JS)
        except Exception as exc:
            return {"err": str(exc)}

    def _worker() -> None:
        time.sleep(3.0)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        win.evaluate_js("window.__MINIAI_AUTO_APPROVE=true")
        bridge.push_status()
        time.sleep(1.0)
        prompt = (
            "Write twelve sentences about mitochondria for a curious student. "
            "Plain prose only. Do not call any tools."
        )
        win.evaluate_js(
            f"""
            (function(){{
              const c = document.getElementById('composer');
              c.value = {prompt!r};
              document.getElementById('btn-send').click();
              return true;
            }})();
            """
        )
        deadline = time.time() + 180
        captured = False
        while time.time() < deadline:
            time.sleep(0.35)
            probe = _probe()
            result["probe"] = probe
            print(f"probe={probe}")
            if isinstance(probe, dict) and probe.get("hasStream") and (
                probe.get("streamLen") or 0
            ) >= 24:
                if _capture_full(OUT):
                    result["ok"] = True
                    result["note"] = "mid-stream"
                    captured = True
                break
            if (
                isinstance(probe, dict)
                and probe.get("hasAnswer")
                and not probe.get("isStop")
            ):
                if _capture_full(OUT):
                    result["ok"] = True
                    result["note"] = "finished-too-fast"
                    captured = True
                break
        if not captured:
            result["note"] = "timeout"
            _capture_full(OUT)
            result["ok"] = OUT.is_file()
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
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.start_status_loop()

    win.events.loaded += _on_loaded
    threading.Thread(target=_worker, daemon=True).start()
    webview.start()
    print(
        f"RESULT_OK={result['ok']} NOTE={result['note']!r} "
        f"OUT_EXISTS={OUT.is_file()} probe={result['probe']}"
    )
    return 0 if result["ok"] and OUT.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
