"""Round 7d Part 5: real-interaction screenshots (folder ticket / verify / decline)."""

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
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v12_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

import ctypes
from ctypes import wintypes


def _set_size(w: int, h: int) -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, "MiniAI")
    if hwnd:
        user32.SetWindowPos(hwnd, 0, 0, 0, int(w), int(h), 0x0002 | 0x0004)
        time.sleep(0.4)


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
    time.sleep(0.2)
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
    except TypeError:
        img = ImageGrab.grab(bbox=box)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print(f"SAVED={path} size={img.size}")
    return True


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


def _assert_and_capture(win, scene: str, assert_js: str, *, retries: int = 4) -> dict:
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
            txt_path = OUT / f"actual_v12_{scene}.txt"
            png_path = OUT / f"actual_v12_{scene}.png"
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


def _wait_ticket(win, deadline: float) -> bool:
    while time.time() < deadline:
        probe = _js(
            win,
            """
            (function(){
              const t=document.querySelector('.ticket:not(.done)');
              return !!(t && t.querySelector('.btn'));
            })()
            """,
        )
        if probe is True or probe == "true":
            return True
        time.sleep(1.0)
    return False


def _click_approve(win) -> bool:
    return bool(
        _js(
            win,
            """
            (function(){
              const t=document.querySelector('.ticket:not(.done)');
              if(!t) return false;
              const primary=t.querySelector('.btn.primary')||t.querySelector('.btn');
              if(primary) primary.click();
              return !!primary;
            })()
            """,
        )
    )


def _click_deny(win) -> bool:
    return bool(
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
    )


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
    fixture = Path(tempfile.mkdtemp(prefix="miniai_v12_fx_"))

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

        # --- Scene 1: folder-create ticket ---
        folder = fixture / "V12TestFolder"
        bridge.send_message(
            f"Make a folder called V12TestFolder at {folder}. "
            "Use create_folder exactly once. Wait for my approval."
        )
        _wait_ticket(win, time.time() + 300)
        results.append(
            _assert_and_capture(
                win,
                "folder_ticket",
                """
                (function(){
                  const t=document.querySelector('.ticket:not(.done)');
                  if(!t) return false;
                  const txt=t.innerText||'';
                  return /Create folder/i.test(txt) && /Don.?t create/i.test(txt);
                })()
                """,
            )
        )
        _click_approve(win)
        # Wait for turn to finish before next scene
        deadline = time.time() + 180
        while time.time() < deadline:
            busy = _js(
                win,
                "!!(document.body && document.body.classList.contains('busy'))",
            )
            if busy is False or busy == "false" or busy == 0:
                # also check no open ticket
                open_t = _js(
                    win,
                    "!!document.querySelector('.ticket:not(.done)')",
                )
                if open_t is False or open_t == "false":
                    break
            time.sleep(1.0)
        time.sleep(1.0)

        # --- Scene 2: delete → green verify node ---
        _js(win, "document.getElementById('btn-new-chat').click()")
        time.sleep(0.6)
        doomed = fixture / f"v12_delete_me_{os.getpid()}.txt"
        doomed.write_text("delete-me-round7d\n", encoding="utf-8")
        bridge.send_message(
            f"Delete the file at {doomed} using delete_file. "
            "After it succeeds, confirm it is gone."
        )
        if _wait_ticket(win, time.time() + 300):
            _click_approve(win)
        deadline2 = time.time() + 240
        while time.time() < deadline2:
            probe = _js(
                win,
                """
                (function(){
                  const v=[...document.querySelectorAll('.step[data-k=\"verify\"]')];
                  const txt=v.map(s=>s.innerText||'').join('\\n');
                  const ok=/Recycle Bin|File exists|Checked the claim|Checked the disk/i.test(txt);
                  return {n:v.length, ok:ok, sample:txt.slice(0,200)};
                })()
                """,
            )
            print(f"VERIFY_PROBE={probe!r}")
            if isinstance(probe, dict) and probe.get("ok") and probe.get("n", 0) >= 1:
                break
            time.sleep(1.5)
        results.append(
            _assert_and_capture(
                win,
                "verify_delete",
                """
                (function(){
                  const v=document.querySelector('.step[data-k=\"verify\"]');
                  if(!v) return false;
                  const txt=v.innerText||'';
                  const fp=(document.getElementById('fp-chk-n')||{}).textContent||'0';
                  const n=parseInt(fp,10)||0;
                  return /Checked|Recycle Bin|File/i.test(txt) && n>=1;
                })()
                """,
            )
        )

        # --- Scene 3: declined create with new wording ---
        _js(win, "document.getElementById('btn-new-chat').click()")
        time.sleep(0.6)
        dest = fixture / f"v12_declined_{os.getpid()}.txt"
        if dest.exists():
            dest.unlink()
        bridge.send_message(
            f"Create a text file at {dest} with content hello-round7d. "
            "Use create_file exactly once."
        )
        if _wait_ticket(win, time.time() + 300):
            _click_deny(win)
        deadline3 = time.time() + 200
        while time.time() < deadline3:
            probe = _js(
                win,
                """
                (function(){
                  const body=document.body?(document.body.innerText||''):'';
                  const denied=document.querySelector('.step[data-k=\"denied\"]');
                  return !!(denied && /You declined, so nothing was changed/i.test(body));
                })()
                """,
            )
            if probe is True or probe == "true":
                break
            time.sleep(1.0)
        results.append(
            _assert_and_capture(
                win,
                "declined_wording",
                """
                (function(){
                  const body=document.body?(document.body.innerText||''):'';
                  const denied=document.querySelector('.step[data-k=\"denied\"]');
                  return !!(denied && /You declined, so nothing was changed/i.test(body));
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
        (OUT / "actual_v12_summary.json").write_text(
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
