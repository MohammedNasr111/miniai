"""Part 5: real-app UI screenshots for QA Round 1 (idle / running / approval / done)."""

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
_chats = Path(tempfile.mkdtemp(prefix="miniai_chats_qa1_"))
os.environ["MINIAI_CHATS_DIR"] = str(_chats)

from tests.support import use_temp_data

use_temp_data()

OUT = PROJECT_ROOT / "app" / "design"
PROMPTS = [
    ("greeting", "Hi, what can you do?"),
    ("math", "What is 17% of 2,350?"),
    ("code", "Write a Python function that checks if a string is a palindrome, with tests, and run them."),
]


def _capture_window(path: Path) -> bool:
    from scripts.miniai_capture import capture_miniai_window

    return capture_miniai_window(path)

def _probe(js: str):
    import webview

    try:
        return webview.windows[0].evaluate_js(js)
    except Exception as exc:
        return {"err": str(exc)}


PROBE_JS = """
(function(){
  const sum = document.querySelector('.activity summary');
  const t = sum ? sum.textContent : '';
  return {
    summary: (t||'').slice(0,120),
    spinner: !!document.querySelector('.spinner'),
    user: !!document.querySelector('.msg-user'),
    userText: (document.querySelector('.msg-user')||{}).textContent||'',
    approval: !!document.querySelector('.approval'),
    waiting: t.indexOf('Waiting for your approval') >= 0,
    worked: t.indexOf('Worked for') >= 0,
    sendDisabled: !!(document.getElementById('btn-send')||{}).disabled,
    stopVisible: !!(document.getElementById('btn-stop') && !document.getElementById('btn-stop').hidden)
  };
})();
"""


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

    results: dict[str, bool] = {}

    def _worker() -> None:
        time.sleep(2.5)
        win = webview.windows[0]
        apply_dark_titlebar(win)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)
        # Manual approvals so we can capture the approval card.
        win.evaluate_js("window.__MINIAI_AUTO_APPROVE=false")
        bridge.push_status()
        time.sleep(0.6)
        results["idle"] = _capture_window(OUT / "qa1_idle.png")

        for key, prompt in PROMPTS:
            print(f"=== prompt {key} ===")
            win.evaluate_js(
                f"""
                (function(){{
                  const c = document.getElementById('composer');
                  c.value = {prompt!r};
                  document.getElementById('btn-send').click();
                }})();
                """
            )
            running_ok = False
            approval_ok = False
            done_ok = False
            deadline = time.time() + 420
            while time.time() < deadline:
                probe = _probe(PROBE_JS)
                print(f"PROBE[{key}]={probe!r}")
                if (
                    isinstance(probe, dict)
                    and not running_ok
                    and probe.get("user")
                    and (probe.get("spinner") or probe.get("waiting"))
                ):
                    time.sleep(0.3)
                    running_ok = _capture_window(OUT / f"qa1_{key}_running.png")
                    results[f"{key}_running"] = running_ok
                    # Confirm user bubble visible while Working
                    ut = (probe.get("userText") or "")[:80]
                    print(f"USER_BUBBLE[{key}]={ut!r}")

                if (
                    isinstance(probe, dict)
                    and not approval_ok
                    and (probe.get("approval") or probe.get("waiting"))
                ):
                    time.sleep(0.4)
                    approval_ok = _capture_window(OUT / f"qa1_{key}_approval.png")
                    results[f"{key}_approval"] = approval_ok
                    # Approve via UI button if present
                    win.evaluate_js(
                        """
                        (function(){
                          const b = document.querySelector('.approval .btn.primary');
                          if (b && !b.disabled) b.click();
                        })();
                        """
                    )
                    # Also try bridge approve by polling
                    try:
                        req = bridge.poll_approval()
                        if req and req.get("nonce"):
                            bridge.approval_reply(req["nonce"], "yes")
                    except Exception as exc:
                        print(f"approve_err={exc}")

                if (
                    isinstance(probe, dict)
                    and probe.get("worked")
                    and not probe.get("spinner")
                    and not probe.get("waiting")
                ):
                    time.sleep(0.6)
                    done_ok = _capture_window(OUT / f"qa1_{key}_done.png")
                    results[f"{key}_done"] = done_ok
                    break
                time.sleep(1.0)
            if not done_ok:
                _capture_window(OUT / f"qa1_{key}_done.png")
            time.sleep(1.0)

        time.sleep(0.5)
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
    print(f"RESULTS={results}")
    # Minimum: idle + at least one running with user bubble + one done
    ok = results.get("idle") and any(
        results.get(f"{k}_running") for k, _ in PROMPTS
    ) and any(results.get(f"{k}_done") for k, _ in PROMPTS)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
