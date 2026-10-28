"""Round 7c Part 6: real-interaction screenshots for declined / web / title."""

from __future__ import annotations

import hashlib
import json
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
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v11_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

# Reuse capture helpers from v10 by importing after path setup
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "capture_v10_ui", PROJECT_ROOT / "scripts" / "capture_v10_ui.py"
)
# Don't exec full v10 main — copy the small helpers locally.

import ctypes
from ctypes import wintypes


def _set_size(w: int, h: int) -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if hwnd:
        user32.SetWindowPos(hwnd, 0, 0, 0, int(w), int(h), 0x0002 | 0x0004)
        time.sleep(0.4)


def _capture(path: Path) -> bool:
    from scripts.miniai_capture import capture_miniai_window

    return capture_miniai_window(path)



def _js(win, code: str):
    try:
        return win.evaluate_js(code)
    except Exception as exc:
        return {"err": str(exc)}


def _visible_text(win) -> str:
    t = _js(
        win,
        "(document.body && document.body.innerText) ? document.body.innerText : ''",
    )
    return str(t or "")


def _assert_and_capture(win, scene: str, assert_js: str, *, retries: int = 3) -> dict:
    meta = {
        "scene": scene,
        "ok": False,
        "assert": assert_js.strip(),
        "png": "",
        "txt": "",
        "md5": "",
        "error": "",
    }
    for attempt in range(1, retries + 1):
        got = _js(win, assert_js)
        print(f"ASSERT {scene} try={attempt} -> {got!r}")
        if got is True or got == "true" or got == 1:
            time.sleep(0.5)
            text = _visible_text(win)
            txt_path = OUT / f"actual_v11_{scene}.txt"
            png_path = OUT / f"actual_v11_{scene}.png"
            txt_path.write_text(text, encoding="utf-8")
            if not _capture(png_path):
                meta["error"] = "capture failed"
                continue
            digest = hashlib.md5(png_path.read_bytes()).hexdigest()
            meta.update(
                {
                    "ok": True,
                    "png": png_path.name,
                    "txt": txt_path.name,
                    "md5": digest,
                }
            )
            return meta
        time.sleep(1.0)
    meta["error"] = f"assert failed after {retries}"
    print(f"FAILED {scene}")
    return meta


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
    results: list[dict] = []

    def _worker() -> None:
        time.sleep(3.5)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.push_status()
        _set_size(1280, 860)
        time.sleep(1.0)
        _js(win, "document.getElementById('btn-new-chat').click()")
        time.sleep(0.6)

        # --- Scene: declined create + muted node ---
        dest = Path(tempfile.gettempdir()) / f"miniai_declined_{os.getpid()}.txt"
        if dest.exists():
            dest.unlink()
        bridge.send_message(
            f"Create a text file at {dest} with content hello-round7c. "
            "Use create_file exactly once."
        )
        deadline = time.time() + 300
        while time.time() < deadline:
            probe = _js(
                win,
                """
                (function(){
                  const t=document.querySelector('.ticket:not(.done)');
                  return !!(t && t.querySelector('.btn:not(.primary)'));
                })()
                """,
            )
            if probe is True or probe == "true":
                break
            time.sleep(1.0)
        # Click deny ("Don't write")
        _js(
            win,
            """
            (function(){
              const t=document.querySelector('.ticket:not(.done)');
              if(!t) return false;
              const btns=[...t.querySelectorAll('.btn')];
              const deny=btns.find(b=>!b.classList.contains('primary'))||btns[btns.length-1];
              if(deny) deny.click();
              return !!deny;
            })()
            """,
        )
        deadline2 = time.time() + 180
        while time.time() < deadline2:
            probe = _js(
                win,
                """
                (function(){
                  const denied=document.querySelector('.step[data-k=\"denied\"]');
                  const txt=denied?(denied.innerText||''):'';
                  return !!(denied && /Didn.?t create|declined/i.test(txt));
                })()
                """,
            )
            if probe is True or probe == "true":
                break
            time.sleep(1.0)
        results.append(
            _assert_and_capture(
                win,
                "declined",
                """
                (function(){
                  const denied=document.querySelector('.step[data-k=\"denied\"]');
                  const ticket=document.querySelector('.ticket.done');
                  const txt=denied?(denied.innerText||''):'';
                  const past=/\\bCreated a file\\b/.test(txt);
                  return !!(denied && ticket && /declined|Didn.?t create/i.test(txt) && !past);
                })()
                """,
            )
        )

        # --- Scene: header title ---
        title_ok = _js(
            win,
            """
            (function(){
              const t=(document.getElementById('chat-title')||{}).textContent||'';
              return t && t!=='New chat';
            })()
            """,
        )
        if not (title_ok is True or title_ok == "true"):
            # Force another short message so title updates
            bridge.send_message("Say hi in one word.")
            time.sleep(8)
        results.append(
            _assert_and_capture(
                win,
                "chat_title",
                """
                (function(){
                  const t=(document.getElementById('chat-title')||{}).textContent||'';
                  return !!(t && t!=='New chat' && t.length>2);
                })()
                """,
            )
        )

        # --- Scene: web research sub-steps ---
        _js(win, "document.getElementById('btn-new-chat').click()")
        time.sleep(0.8)
        bridge.send_message(
            "What is the current stable Python release version according to python.org? "
            "Use web_research."
        )
        deadline3 = time.time() + 420
        while time.time() < deadline3:
            probe = _js(
                win,
                """
                (function(){
                  const steps=[...document.querySelectorAll('.step')].map(s=>({
                    k:s.dataset.k, text:(s.innerText||'').slice(0,120)
                  }));
                  const searched=steps.some(s=>/Searched the web/i.test(s.text));
                  const pages=steps.some(s=>/Read \\d+ pages?/i.test(s.text));
                  const out=steps.some(s=>s.k==='out');
                  return {searched, pages, out, n:steps.length};
                })()
                """,
            )
            print(f"WEB_PROBE={probe!r}")
            if isinstance(probe, dict) and probe.get("searched") and (
                probe.get("pages") or probe.get("out")
            ):
                # Prefer waiting for pages sub-step
                if probe.get("pages") or time.time() > deadline3 - 60:
                    break
            time.sleep(1.5)
        results.append(
            _assert_and_capture(
                win,
                "web_substeps",
                """
                (function(){
                  const steps=[...document.querySelectorAll('.step')].map(s=>(s.innerText||''));
                  const searched=steps.some(t=>/Searched the web/i.test(t));
                  const pages=steps.some(t=>/Read \\d+ pages?/i.test(t));
                  const lilac=!!document.querySelector('.step[data-k=\"out\"]');
                  return searched && (pages || lilac);
                })()
                """,
            )
        )

        md5s = [r["md5"] for r in results if r.get("md5")]
        summary = {
            "results": results,
            "unique_md5": len(md5s) == len(set(md5s)) and len(md5s) == len(results),
            "ok": all(r.get("ok") for r in results),
        }
        (OUT / "actual_v11_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        print("SUMMARY", json.dumps(summary))
        print(f"DONE ok={summary['ok']} unique={summary['unique_md5']}")
        try:
            win.destroy()
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    webview.create_window(
        "MiniAI",
        url=index_uri(),
        js_api=bridge.js_api,
        width=1280,
        height=860,
        background_color="#121821",
    )
    bridge.window = webview.windows[0]
    try:
        webview.start(debug=False, private_mode=True)
    except TypeError:
        webview.start(debug=False)
    t.join(timeout=30)
    ok = all(r.get("ok") for r in results) if results else False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
