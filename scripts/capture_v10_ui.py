"""Round 7b Part 3: REAL-interaction screenshots (no DOM scene injection).

Launches the same target as the Start-menu shortcut (pythonw -m app / in-process
equivalent), drives the real composer + agent loop, asserts DOM before each
capture, and writes actual_v10_<scene>.{png,txt}.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "app" / "design"
os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")

_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_v10_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

FIXTURE = Path(tempfile.mkdtemp(prefix="miniai_dl_"))
for name in ("SetupA.exe", "SetupB.exe", "SetupC.exe", "notes.txt"):
    (FIXTURE / name).write_bytes(b"MZ fake installer " + name.encode() + b"\0" * 64)


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


def _assert_and_capture(
    win,
    scene: str,
    assert_js: str,
    *,
    retries: int = 3,
    settle: float = 0.5,
) -> dict:
    """Assert DOM, write txt+png. Never save PNG if assert fails after retries."""
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
            time.sleep(settle)
            text = _visible_text(win)
            txt_path = OUT / f"actual_v10_{scene}.txt"
            png_path = OUT / f"actual_v10_{scene}.png"
            txt_path.write_text(text, encoding="utf-8")
            if not _capture(png_path):
                meta["error"] = "capture failed"
                continue
            digest = hashlib.md5(png_path.read_bytes()).hexdigest()
            meta.update(
                {
                    "ok": True,
                    "png": str(png_path.name),
                    "txt": str(txt_path.name),
                    "md5": digest,
                    "error": "",
                }
            )
            return meta
        time.sleep(1.0)
    meta["error"] = f"assert failed after {retries} tries (last={got!r})"
    print(f"FAILED {scene}: {meta['error']}")
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

    # Same target as Start menu shortcut: -m app, working dir = project root.
    print(f"FIXTURE={FIXTURE}")
    print(f"CHATS={_chats}")
    print("Launch mode: in-process webview (same Target/Args as MiniAI.lnk)")

    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    bridge = AppBridge()
    set_approver(bridge.approver)
    reset_session()
    results: list[dict] = []
    state: dict[str, object] = {"done": False}

    def _worker() -> None:
        time.sleep(3.5)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        apply_window_icon(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        bridge.push_status()
        _set_size(1280, 860)
        time.sleep(1.0)

        # Ensure empty new chat
        _js(win, "document.getElementById('btn-new-chat').click()")
        time.sleep(0.8)
        results.append(
            _assert_and_capture(
                win,
                "empty",
                """
                (function(){
                  const empty = !!document.querySelector('.empty');
                  const ticket = !!document.querySelector('.ticket');
                  const fpEmpty = document.getElementById('fp-empty');
                  const fpOk = fpEmpty && !fpEmpty.hidden;
                  const badLabel = !!document.querySelector('label[for=composer]');
                  return empty && !ticket && fpOk && !badLabel;
                })()
                """,
            )
        )

        # Real move prompt — exact file destinations (parent Installers is created by move_files).
        dest_dir = FIXTURE / "Installers"
        moves_hint = ", ".join(
            f"{FIXTURE / n} -> {dest_dir / n}"
            for n in ("SetupA.exe", "SetupB.exe", "SetupC.exe")
        )
        prompt = (
            f"Call move_files once with exactly these three moves: {moves_hint}. "
            "Do not change the destinations."
        )
        bridge.send_message(prompt)
        # Wait for pending ticket
        ticket_ok = False
        deadline = time.time() + 420
        while time.time() < deadline:
            probe = _js(
                win,
                """
                (function(){
                  const t = document.querySelector('.ticket:not(.done)');
                  if (!t) return {pending:false};
                  const h = (t.querySelector('h4')||{}).textContent||'';
                  const primary = t.querySelector('.btn.primary');
                  return {
                    pending: true,
                    heading: h,
                    hasPrimary: !!primary,
                    label: primary ? primary.textContent : ''
                  };
                })()
                """,
            )
            print(f"TICKET_PROBE={probe!r}")
            if isinstance(probe, dict) and probe.get("pending") and probe.get("hasPrimary"):
                ticket_ok = True
                break
            # Still working?
            busy = _js(
                win,
                "!!(document.getElementById('btn-send')||{}).classList.contains('is-stop')",
            )
            if busy is False and time.time() > deadline - 300:
                # Agent finished without ticket — fail later
                pass
            time.sleep(1.2)

        if ticket_ok:
            results.append(
                _assert_and_capture(
                    win,
                    "ticket_pending",
                    """
                    (function(){
                      const t = document.querySelector('.ticket:not(.done)');
                      return !!(t && t.querySelector('.btn.primary'));
                    })()
                    """,
                )
            )
            # Click the real Move button
            _js(
                win,
                """
                (function(){
                  const b = document.querySelector('.ticket:not(.done) .btn.primary');
                  if (b) b.click();
                  return !!b;
                })()
                """,
            )
            # Wait for collapsed ticket + answer
            deadline2 = time.time() + 300
            while time.time() < deadline2:
                probe = _js(
                    win,
                    """
                    (function(){
                      return {
                        doneTicket: !!document.querySelector('.ticket.done'),
                        verify: !!document.querySelector('.step[data-k=\"verify\"]'),
                        change: !!document.querySelector('.step[data-k=\"change\"]'),
                        answer: !!document.querySelector('.answer:not([hidden]) .answer-md, .answer:not([hidden]) p'),
                        stop: !!(document.getElementById('btn-send')||{}).classList.contains('is-stop')
                      };
                    })()
                    """,
                )
                print(f"AFTER_MOVE={probe!r}")
                if (
                    isinstance(probe, dict)
                    and probe.get("doneTicket")
                    and (probe.get("verify") or probe.get("change"))
                    and (probe.get("answer") or not probe.get("stop"))
                ):
                    break
                time.sleep(1.0)
            results.append(
                _assert_and_capture(
                    win,
                    "ticket_done",
                    """
                    (function(){
                      return !!document.querySelector('.ticket.done')
                        && (!!document.querySelector('.step[data-k=\"verify\"]')
                            || !!document.querySelector('.step[data-k=\"change\"]'));
                    })()
                    """,
                )
            )
        else:
            results.append(
                {
                    "scene": "ticket_pending",
                    "ok": False,
                    "error": "no pending ticket from real agent",
                    "png": "",
                    "txt": "",
                    "md5": "",
                }
            )
            results.append(
                {
                    "scene": "ticket_done",
                    "ok": False,
                    "error": "skipped (no pending ticket)",
                    "png": "",
                    "txt": "",
                    "md5": "",
                }
            )

        # Web question — capture mid-stream / with lilac out nodes
        bridge.send_message(
            "What is the latest stable Python version according to python.org?"
        )
        deadline3 = time.time() + 240
        web_meta = None
        while time.time() < deadline3:
            probe = _js(
                win,
                """
                (function(){
                  return {
                    out: !!document.querySelector('.step[data-k=\"out\"]'),
                    live: !!document.querySelector('.step.live[data-k=\"out\"]'),
                    stream: !!document.querySelector('.stream-raw, .caret'),
                    stop: !!(document.getElementById('btn-send')||{}).classList.contains('is-stop')
                  };
                })()
                """,
            )
            print(f"WEB_PROBE={probe!r}")
            if isinstance(probe, dict) and probe.get("out"):
                web_meta = _assert_and_capture(
                    win,
                    "web_stream",
                    "!!document.querySelector('.step[data-k=\"out\"]')",
                )
                break
            time.sleep(0.8)
        if web_meta is None:
            results.append(
                {
                    "scene": "web_stream",
                    "ok": False,
                    "error": "no lilac out nodes",
                    "png": "",
                    "txt": "",
                    "md5": "",
                }
            )
        else:
            results.append(web_meta)
        # Let web turn finish so footprint updates
        deadline4 = time.time() + 180
        while time.time() < deadline4:
            stop = _js(
                win,
                "!!(document.getElementById('btn-send')||{}).classList.contains('is-stop')",
            )
            if stop is False:
                break
            time.sleep(1.0)

        # Footprint open with real entries
        _js(
            win,
            """
            (function(){
              document.getElementById('app').classList.add('show-foot');
              const btn = document.getElementById('open-foot');
              if (btn) btn.click();
              document.getElementById('app').classList.add('show-foot');
              return true;
            })()
            """,
        )
        time.sleep(0.6)
        results.append(
            _assert_and_capture(
                win,
                "footprint",
                """
                (function(){
                  const body = document.getElementById('fp-body');
                  const empty = document.getElementById('fp-empty');
                  const hasBody = body && !body.hidden;
                  const text = document.body.innerText || '';
                  const sample = /Windows 11 October update/.test(text);
                  return hasBody && !(empty && !empty.hidden) && !sample;
                })()
                """,
            )
        )

        # Palette via real Ctrl+K keydown
        _js(
            win,
            """
            (function(){
              document.getElementById('app').classList.remove('show-foot','show-rail');
              const ev = new KeyboardEvent('keydown', {key:'k', ctrlKey:true, bubbles:true});
              document.dispatchEvent(ev);
              return !document.getElementById('palette').hidden;
            })()
            """,
        )
        time.sleep(0.4)
        results.append(
            _assert_and_capture(
                win,
                "palette",
                "!(document.getElementById('palette')||{hidden:true}).hidden",
            )
        )
        _js(win, "document.getElementById('palette').hidden = true")

        # Narrow 640 px — rail slide-over control visible
        _set_size(640, 860)
        time.sleep(0.6)
        results.append(
            _assert_and_capture(
                win,
                "narrow640",
                """
                (function(){
                  const btn = document.getElementById('open-rail');
                  const style = btn ? getComputedStyle(btn).display : 'none';
                  return style !== 'none';
                })()
                """,
            )
        )

        # Hash uniqueness
        md5s = [r["md5"] for r in results if r.get("md5")]
        unique = len(md5s) == len(set(md5s))
        summary = {
            "fixture": str(FIXTURE),
            "results": results,
            "unique_md5": unique,
            "md5s": md5s,
        }
        (OUT / "actual_v10_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        print(f"SUMMARY unique_md5={unique} ok={sum(1 for r in results if r.get('ok'))}/{len(results)}")
        state["done"] = True
        state["summary"] = summary
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
        min_size=(600, 500),
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

    summary = state.get("summary") or {}
    results = summary.get("results") or []
    ok_n = sum(1 for r in results if r.get("ok"))
    # Require empty + palette + narrow at minimum; ticket/web depend on model
    required = {"empty", "palette", "narrow640"}
    ok_required = all(
        any(r.get("scene") == s and r.get("ok") for r in results) for s in required
    )
    unique = bool(summary.get("unique_md5"))
    print(f"DONE ok={ok_n} required={ok_required} unique={unique}")
    return 0 if ok_required and unique and ok_n >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
