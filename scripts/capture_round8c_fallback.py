"""Round 8c/8d: capture forced 429 reason + Footprint entries (mocked HTTP).

Round 8d: assert #fp-body is visible with ≥1 "Sent to Google Gemini" line
BEFORE saving the PNG, and that the run heading is the user's request.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "app" / "design"
os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_r8c_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

import ctypes
from ctypes import wintypes

USER_ASK = "Write a tiny hello webpage in the workspace."


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

    from app.prefs import set_cloud_experimental, set_gemini_quota_hit_at
    from app.webview_approver import AppBridge
    from llm.base import ChatMessage, ChatResponse
    from llm.gemini.provider import GeminiProvider, GeminiQuotaError
    from security.gemini_key import save_key

    set_gemini_quota_hit_at(None)
    set_cloud_experimental(True)
    save_key("AIzaSyFAKE-R8C-CAPTURE-KEY-0001")

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
        try:
            bridge.set_cloud_experimental(True)
        except Exception:
            pass

        # Mock Gemini: two successful requests, then 429 with RESOURCE_EXHAUSTED.
        http = MagicMock()
        models = MagicMock()
        models.status_code = 200
        models.json.return_value = {"data": [{"id": "gemini-flash-lite-latest"}]}
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {
            "choices": [
                {
                    "message": {"content": "draft", "tool_calls": None},
                    "finish_reason": "stop",
                }
            ]
        }
        fail = MagicMock()
        fail.status_code = 429
        fail.json.return_value = {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exceeded for AIzaSySHOULD-REDACT",
            }
        }
        fail.text = "{}"
        posts = [ok, fail]
        http.get.return_value = models
        http.post.side_effect = lambda *a, **k: posts.pop(0) if posts else fail
        gem = GeminiProvider(api_key="AIzaSyFAKE-R8C-CAPTURE-KEY-0001", session=http)

        calls = {"n": 0}

        def _fake_rounds(prov, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1 and isinstance(prov, GeminiProvider):
                # Two recorded successes via real chat, then quota on third logical step.
                from agent.cloud_routing import note_cloud_http_sent

                note_cloud_http_sent({"body_chars": 180, "message_chars": 40})
                note_cloud_http_sent({"body_chars": 260, "message_chars": 55})
                raise GeminiQuotaError(
                    http_status=429,
                    google_status="RESOURCE_EXHAUSTED",
                    google_message="Quota exceeded",
                )
            return ChatResponse(
                content="Finished on this PC after Gemini stopped.",
                finish_reason="stop",
            )

        from llm.gemini import provider as gem_mod
        import scripts.chat as chat_mod

        found_reason = False
        found_fp = False
        body = ""
        with patch.object(gem_mod, "GeminiProvider", return_value=gem):
            with patch.object(chat_mod, "run_tool_rounds", side_effect=_fake_rounds):
                try:
                    bridge.prepare_next_cloud(True)
                    bridge.send_message(USER_ASK, cloud=True)
                except Exception as exc:
                    print("SEND_ERR", type(exc).__name__, str(exc)[:160])

                deadline = time.time() + 180
                while time.time() < deadline:
                    body = _js(
                        win,
                        "(document.body && document.body.innerText) || ''",
                    )
                    text = body if isinstance(body, str) else str(body)
                    if "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
                        found_reason = True
                    if "Sent to Google Gemini" in text:
                        found_fp = True
                    if found_reason and (
                        "stopped partway" in text or "wasn't used" in text
                    ):
                        break
                    time.sleep(1.0)

        # Open Footprint panel (desktop always shows .foot; mobile needs show-foot).
        opened = _js(
            win,
            """
            (function(){
              var app = document.getElementById('app');
              if (app) app.classList.add('show-foot');
              var b = document.getElementById('open-foot');
              if (b) b.click();
              if (app) app.classList.add('show-foot');
              var body = document.getElementById('fp-body');
              var empty = document.getElementById('fp-empty');
              var left = document.getElementById('fp-left');
              var leftText = (left && left.innerText) || '';
              var ask = '';
              var p = document.querySelector('.run .ask > p');
              if (p) ask = (p.textContent || '').trim();
              var gemLines = (leftText.match(/Sent to Google Gemini/g) || []).length;
              return {
                fpVisible: !!(body && !body.hidden),
                emptyHidden: !!(empty && empty.hidden),
                gemLines: gemLines,
                ask: ask,
                leftText: leftText.slice(0, 400)
              };
            })()
            """,
        )
        time.sleep(0.5)
        # Re-check after layout settle
        check = _js(
            win,
            """
            (function(){
              var app = document.getElementById('app');
              if (app) app.classList.add('show-foot');
              var body = document.getElementById('fp-body');
              var empty = document.getElementById('fp-empty');
              var left = document.getElementById('fp-left');
              var leftText = (left && left.innerText) || '';
              var ask = '';
              var p = document.querySelector('.run .ask > p');
              if (p) ask = (p.textContent || '').trim();
              var gemLines = (leftText.match(/Sent to Google Gemini/g) || []).length;
              return {
                fpVisible: !!(body && !body.hidden),
                emptyHidden: !!(empty && empty.hidden),
                gemLines: gemLines,
                ask: ask,
                askOk: ask.indexOf('Write a tiny hello webpage') === 0,
                notWorking: ask !== '(working)' && ask !== '…' && ask !== '...',
                leftText: leftText.slice(0, 400)
              };
            })()
            """,
        )
        print("FP_CHECK", check)
        print("FP_OPENED", opened)

        ok_fp = False
        ok_ask = False
        if isinstance(check, dict):
            ok_fp = bool(check.get("fpVisible")) and int(check.get("gemLines") or 0) >= 1
            ok_ask = bool(check.get("askOk")) and bool(check.get("notWorking"))
        if not ok_fp:
            print(
                "ASSERT_FAIL footprint: need #fp-body visible with "
                ">=1 'Sent to Google Gemini' before save; got",
                check,
            )
            try:
                win.destroy()
            except Exception:
                pass
            return

        path = OUT / "actual_r8c_cloud_quota_footprint.png"
        _capture(path)
        text = body if isinstance(body, str) else str(body)
        (OUT / "actual_r8c_cloud_quota_footprint.txt").write_text(
            text
            + "\n\n--- FP_CHECK ---\n"
            + str(check)
            + "\n",
            encoding="utf-8",
        )
        print(
            "SCENE_R8C",
            "PASS" if (found_reason and found_fp and ok_fp and ok_ask) else "FAIL",
            "reason=",
            found_reason,
            "fp=",
            found_fp,
            "fp_open=",
            ok_fp,
            "ask_ok=",
            ok_ask,
        )
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
    # Ensure patch is available in nested scope
    from unittest.mock import patch  # noqa: F401

    raise SystemExit(main())
