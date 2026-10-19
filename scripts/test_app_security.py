"""Stage 11b: navigation lock, open_external allowlist, approval nonces."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def test_open_external_schemes() -> None:
    from app.webview_approver import AppBridge

    bridge = AppBridge()
    with patch("os.startfile") as startfile:
        ok_http = bridge.open_external("https://example.com/x")
        ok_http2 = bridge.open_external("http://example.com/")
        bad_js = bridge.open_external("javascript:alert(1)")
        bad_file = bridge.open_external("file:///C:/Windows/notepad.exe")
        bad_data = bridge.open_external("data:text/html,hi")
        _check(
            "open_external_schemes",
            ok_http.get("ok")
            and ok_http2.get("ok")
            and not bad_js.get("ok")
            and not bad_file.get("ok")
            and not bad_data.get("ok")
            and startfile.call_count == 2,
            f"http={ok_http} js={bad_js} file={bad_file} data={bad_data} "
            f"starts={startfile.call_count}",
        )


def test_approval_wrong_nonce() -> None:
    from app.webview_approver import AppBridge, WebviewApprover
    from security.approver import set_approver
    from security.gate import PermissionDenied, Tier, check_permission, reset_session

    bridge = AppBridge()
    set_approver(bridge.approver)
    reset_session()
    result: dict = {}

    def _ask() -> None:
        try:
            check_permission("browser_open", Tier.CONFIRM, "Open in browser:\nhttps://example.com")
            result["approved"] = True
        except PermissionDenied:
            result["denied"] = True
        except Exception as exc:
            result["err"] = repr(exc)

    t = threading.Thread(target=_ask, daemon=True)
    t.start()
    # Wait until pending
    deadline = time.time() + 5
    pending = None
    while time.time() < deadline:
        pending = bridge.approver.take_pending()
        if pending and pending.get("id"):
            break
        time.sleep(0.05)
    if not pending:
        _check("approval_wrong_nonce", False, "no pending approval")
        bridge.approver.force_deny()
        t.join(timeout=2)
        return
    nonce = pending["id"]
    # Wrong id must not approve
    ok_wrong = bridge.approver.resolve("0" * 32, "yes")
    time.sleep(0.2)
    still = bridge.approver.take_pending()
    ok_right = bridge.js_api.approval_reply(nonce, "yes")
    t.join(timeout=5)
    _check(
        "approval_wrong_nonce",
        (not ok_wrong)
        and still is not None
        and ok_right
        and result.get("approved") is True,
        f"wrong={ok_wrong} still={still is not None} right={ok_right} result={result}",
    )


def test_link_click_and_nav_lock() -> None:
    try:
        import webview
    except ImportError as exc:
        _check("link_click_nav_lock", False, f"no webview: {exc}")
        return

    from app.main import INDEX, _is_allowed_url, index_uri
    from app.webview_approver import AppBridge

    bridge = AppBridge()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    state: dict = {"url0": None, "url1": None, "ext": None, "reverted": None}

    def _run() -> None:
        time.sleep(1.8)
        win = webview.windows[0]
        try:
            state["url0"] = win.get_current_url()
            # Inject a link and click it via the same delegated handler path.
            win.evaluate_js(
                """
                (function(){
                  const a = document.createElement('a');
                  a.href = 'https://example.com/nav-test';
                  a.textContent = 'x';
                  a.id = 'nav-test-link';
                  document.body.appendChild(a);
                  a.click();
                  return location.href;
                })();
                """
            )
            time.sleep(0.6)
            state["url1"] = win.get_current_url()
            state["ext"] = list(bridge._external_log)
            # Force navigation away; loaded handler should pull back.
            win.load_url("https://example.com/")
            deadline = time.time() + 8
            while time.time() < deadline:
                cur = win.get_current_url() or ""
                if _is_allowed_url(cur):
                    state["reverted"] = cur
                    break
                time.sleep(0.2)
            else:
                state["reverted"] = win.get_current_url()
        finally:
            try:
                win.destroy()
            except Exception:
                pass

    # Attach navigation lock like main.py
    allowed = index_uri()

    def _on_loaded() -> None:
        try:
            current = win.get_current_url() or ""
        except Exception:
            current = ""
        if not _is_allowed_url(current):
            win.load_url(allowed)

    win = webview.create_window(
        "MiniAI",
        allowed,
        js_api=bridge.js_api,
        width=900,
        height=600,
        background_color="#0D0E11",
    )
    bridge.window = win
    win.events.loaded += _on_loaded
    webview.start(_run)

    index_path = str(INDEX.resolve()).lower().replace("\\", "/")
    u0 = (state.get("url0") or "").lower().replace("\\", "/")
    u1 = (state.get("url1") or "").lower().replace("\\", "/")
    unchanged = "example.com" not in u1 and (
        "index.html" in u1 or index_path.split(":/")[-1] in u1.replace("%3a", ":")
    )
    ext_ok = any("example.com/nav-test" in x for x in (state.get("ext") or []))
    rev = (state.get("reverted") or "").lower()
    reverted = _is_allowed_url(state.get("reverted") or "") or "index.html" in rev
    _check(
        "link_click_nav_lock",
        unchanged and ext_ok and reverted,
        f"url0={state.get('url0')!r} url1={state.get('url1')!r} "
        f"ext={state.get('ext')!r} reverted={state.get('reverted')!r}",
    )


def test_csp_meta() -> None:
    html = (PROJECT_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    has_csp = "Content-Security-Policy" in html
    has_default = "default-src 'none'" in html
    has_script = "script-src 'self'" in html
    no_inline_script = "<script>" not in html.replace('<script src="app.js"></script>', "")
    no_inline_style_attr = 'style="' not in html
    _check(
        "csp_meta",
        has_csp and has_default and has_script and no_inline_script and no_inline_style_attr,
        f"csp={has_csp} default={has_default} script={has_script} "
        f"no_inline_script={no_inline_script} no_style_attr={no_inline_style_attr}",
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_open_external_schemes()
    test_approval_wrong_nonce()
    test_csp_meta()
    test_link_click_and_nav_lock()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
