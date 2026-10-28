"""Part 3: capture composer Send/Stop button at 0.5s / 2s / 5s / done."""

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
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v7_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT = PROJECT_ROOT / "app" / "design"
PROBE_JS = """
(function(){
  const b = document.getElementById('btn-send');
  const send = b && b.querySelector('.ico-send');
  const stop = b && b.querySelector('.ico-stop');
  const act = document.querySelector('.activity, .msg-activity, [class*="activity"]');
  const working = !!(document.body.innerText||'').match(/Working/i);
  return {
    isStop: !!(b && b.classList.contains('is-stop')),
    title: b ? (b.getAttribute('title')||'') : '',
    sendHidden: !!(send && send.hidden),
    stopHidden: !!(stop && stop.hidden),
    busyHint: working,
    hasAi: !!document.querySelector('.msg-ai, .msg-assistant, .ai-body'),
    hasUser: !!document.querySelector('.msg-user')
  };
})();
"""


def _capture_full(path: Path):
    from scripts.miniai_capture import capture_miniai_window

    return capture_miniai_window(path)

def _crop_btn(img, out_path: Path):
    """Zoom-crop bottom-right composer button region."""
    from PIL import Image

    w, h = img.size
    # Button sits in composer at bottom-right of content area.
    box = (max(0, w - 220), max(0, h - 160), w - 24, h - 40)
    crop = img.crop(box)
    zoom = crop.resize(
        (crop.size[0] * 3, crop.size[1] * 3), Image.Resampling.NEAREST
    )
    zoom.save(out_path)
    print(f"SAVED_BTN={out_path} crop={box} zoom={zoom.size}")
    return zoom


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
    results: dict = {"probes": {}, "files": {}, "arrow_while_running": False}

    def _probe():
        try:
            return webview.windows[0].evaluate_js(PROBE_JS)
        except Exception as exc:
            return {"err": str(exc)}

    def _shot(label: str):
        full = OUT / f"actual_v7_{label}.png"
        btn = OUT / f"actual_v7_btn_{label}.png"
        img = _capture_full(full)
        if img is None:
            results["files"][label] = False
            return
        _crop_btn(img, btn)
        results["files"][label] = True
        p = _probe()
        results["probes"][label] = p
        print(f"PROBE_{label}={p!r}")
        if isinstance(p, dict) and label != "done":
            # After 0.5s while turn should be running: must be Stop, not arrow.
            if not p.get("isStop") or not p.get("sendHidden"):
                results["arrow_while_running"] = True

    def _worker() -> None:
        time.sleep(3.0)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        win.evaluate_js("window.__MINIAI_AUTO_APPROVE=true")
        bridge.push_status()
        # Wait briefly for UI; model warm-up may still be going.
        time.sleep(1.0)
        t0 = time.time()
        win.evaluate_js(
            """
            (function(){
              const c = document.getElementById('composer');
              c.value = 'Hi, what can you do?';
              document.getElementById('btn-send').click();
              return {
                isStop: document.getElementById('btn-send').classList.contains('is-stop'),
                t: Date.now()
              };
            })();
            """
        )
        print(f"CLICK_AT={time.time() - t0:.3f}")
        # Timed shots from send
        schedule = [("0_5s", 0.5), ("2s", 2.0), ("5s", 5.0)]
        for label, delay in schedule:
            remain = delay - (time.time() - t0)
            if remain > 0:
                time.sleep(remain)
            _shot(label)
        # Wait until done (no is-stop) or timeout
        deadline = time.time() + 240
        while time.time() < deadline:
            p = _probe()
            if isinstance(p, dict) and p.get("hasAi") and not p.get("isStop"):
                break
            time.sleep(0.5)
        _shot("done")
        print(f"RESULTS={results!r}")
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
    print(f"FINAL={results!r}")
    # Persist machine-readable summary
    summary = OUT / "actual_v7_btn_summary.txt"
    summary.write_text(repr(results), encoding="utf-8")
    ok = all(results["files"].get(k) for k in ("0_5s", "2s", "5s", "done"))
    if results["arrow_while_running"]:
        print("NEED_FIX=arrow_while_running")
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
