"""Stage 11b: navigation lock, open_external allowlist, approval nonces."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        calls = [c.args[0] for c in startfile.call_args_list]
        _check(
            "open_external_schemes",
            ok_http.get("ok")
            and ok_http2.get("ok")
            and not bad_js.get("ok")
            and not bad_file.get("ok")
            and not bad_data.get("ok")
            and startfile.call_count == 2
            and calls == ["https://example.com/x", "http://example.com/"],
            f"http={ok_http} js={bad_js} file={bad_file} data={bad_data} "
            f"calls={calls}",
        )


def test_approval_wrong_nonce() -> None:
    from app.webview_approver import AppBridge
    from security.approver import set_approver
    from security.gate import PermissionDenied, Tier, check_permission, reset_session

    bridge = AppBridge()
    set_approver(bridge.approver)
    reset_session()
    result: dict = {}

    def _ask() -> None:
        try:
            check_permission(
                "browser_open", Tier.CONFIRM, "Open in browser:\nhttps://example.com"
            )
            result["approved"] = True
        except PermissionDenied:
            result["denied"] = True
        except Exception as exc:
            result["err"] = repr(exc)

    t = threading.Thread(target=_ask, daemon=True)
    t.start()
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
    ok_wrong = bridge.approver.resolve("0" * 32, "yes")
    time.sleep(0.2)
    still = bridge.approver.take_pending()
    ok_right = bridge.approver.resolve(nonce, "yes")
    t.join(timeout=5)
    _check(
        "approval_wrong_nonce",
        (not ok_wrong)
        and still is not None
        and ok_right
        and result.get("approved") is True,
        f"wrong={ok_wrong} still={still is not None} right={ok_right} result={result}",
    )


def test_js_api_foreign_refused() -> None:
    from app.main import index_uri
    from app.webview_approver import AppBridge

    bridge = AppBridge()
    win = MagicMock()
    win.get_current_url.return_value = "https://evil.example/"
    bridge.window = win
    refused = bridge.js_api.send_message("hi")
    listed = bridge.js_api.list_chats()
    ext = bridge.js_api.open_external("https://example.com")
    # On index URL, open_external path is allowed through the guard.
    win.get_current_url.return_value = index_uri()
    with patch("os.startfile") as startfile:
        ok = bridge.js_api.open_external("https://example.com/ok")
        _check(
            "js_api_foreign_refused",
            refused is None
            and listed == []
            and not ext.get("ok")
            and ok.get("ok")
            and startfile.call_count == 1
            and startfile.call_args.args[0] == "https://example.com/ok",
            f"refused_send={refused} listed={listed} ext={ext} ok={ok} "
            f"calls={startfile.call_args_list}",
        )


def test_csp_meta() -> None:
    html = (PROJECT_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    has_csp = "Content-Security-Policy" in html
    has_default = "default-src 'none'" in html
    has_script = "script-src 'self'" in html
    no_inline_script = "<script>" not in html.replace(
        '<script src="app.js"></script>', ""
    )
    no_inline_style_attr = 'style="' not in html
    _check(
        "csp_meta",
        has_csp
        and has_default
        and has_script
        and no_inline_script
        and no_inline_style_attr,
        f"csp={has_csp} default={has_default} script={has_script} "
        f"no_inline_script={no_inline_script} no_style_attr={no_inline_style_attr}",
    )


def test_nav_starting_cancel_and_link() -> None:
    try:
        import webview
    except ImportError as exc:
        _check("nav_starting_cancel", False, f"no webview: {exc}")
        return

    from app.main import INDEX, _is_allowed_url, index_uri
    from app.nav_lock import (
        attach_native_nav_lock,
        clear_cancel_log,
        get_cancel_log,
    )
    from app.webview_approver import AppBridge

    bridge = AppBridge()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    clear_cancel_log()
    state: dict = {
        "url0": None,
        "url1": None,
        "url_after_force": None,
        "ext": None,
        "attached": False,
    }

    def _run() -> None:
        time.sleep(2.0)
        win = webview.windows[0]
        try:
            state["attached"] = attach_native_nav_lock(
                win, INDEX.resolve(), bridge.open_external
            )
            state["url0"] = win.get_current_url()
            with patch("os.startfile") as startfile:
                win.evaluate_js(
                    """
                    (function(){
                      const a = document.createElement('a');
                      a.href = 'https://example.com/nav-test';
                      a.textContent = 'x';
                      document.body.appendChild(a);
                      a.click();
                      return location.href;
                    })();
                    """
                )
                time.sleep(0.5)
                state["url1"] = win.get_current_url()
                state["ext"] = list(bridge._external_log)
                state["startfile_calls"] = [
                    c.args[0] for c in startfile.call_args_list
                ]
            # Programmatic navigation must be cancelled before it sticks.
            clear_cancel_log()
            win.load_url("https://example.com/")
            time.sleep(1.2)
            state["url_after_force"] = win.get_current_url()
            state["cancels"] = get_cancel_log()
        finally:
            try:
                win.destroy()
            except Exception:
                pass

    allowed = index_uri()

    def _on_loaded() -> None:
        try:
            current = win.get_current_url() or ""
        except Exception:
            current = ""
        if not _is_allowed_url(current):
            win.load_url(allowed)
        attach_native_nav_lock(win, INDEX.resolve(), bridge.open_external)

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

    u0 = state.get("url0") or ""
    u1 = state.get("url1") or ""
    u_force = state.get("url_after_force") or ""
    unchanged_click = "example.com" not in u1 and "index.html" in u1.lower()
    unchanged_force = "example.com" not in u_force and "index.html" in u_force.lower()
    ext_ok = any("example.com/nav-test" in x for x in (state.get("ext") or []))
    cancels = state.get("cancels") or []
    cancel_logged = any(
        "example.com" in uri and reason == "NavigationStarting"
        for uri, reason in cancels
    )
    _check(
        "nav_starting_cancel",
        state.get("attached")
        and unchanged_click
        and unchanged_force
        and ext_ok
        and cancel_logged
        and "index.html" in (u0 or "").lower(),
        f"attached={state.get('attached')} url0={u0!r} url1={u1!r} "
        f"after_force={u_force!r} ext={state.get('ext')!r} "
        f"cancels={cancels!r} startfile={state.get('startfile_calls')!r}",
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_open_external_schemes()
    test_approval_wrong_nonce()
    test_js_api_foreign_refused()
    test_csp_meta()
    test_nav_starting_cancel_and_link()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
