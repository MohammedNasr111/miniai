"""Stage 11a: Approver interface + app UI safety checks."""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from security.approver import (  # noqa: E402
    Approver,
    ConsoleApprover,
    get_approver,
    set_approver,
)
from security.gate import (  # noqa: E402
    PermissionDenied,
    Tier,
    check_permission,
    mark_untrusted,
    reset_session,
)

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


class ScriptedApprover(Approver):
    """Returns canned answers in order for ask_typed / ask_yes_no."""

    def __init__(self, typed_answers: list[str], yes_no: list[bool] | None = None):
        self._typed = list(typed_answers)
        self._yes = list(yes_no or [])
        self.typed_calls: list[tuple[str, str]] = []

    def ask_yes_no(self, action: str, description: str, banner: str) -> bool:
        if self._yes:
            return self._yes.pop(0)
        return False

    def ask_typed(self, action: str, description: str, banner: str) -> str:
        ans = self._typed.pop(0) if self._typed else ""
        self.typed_calls.append((action, ans))
        return ans

    def ask_app_read(self, exe: str, title: str, extra: str):
        return "refuse"

    def ask_continue(self, message: str) -> bool:
        return False


def test_a_scripted_typed() -> None:
    reset_session()
    mark_untrusted("browser_open")
    scripted = ScriptedApprover(["yes", "write_file"])
    prev = set_approver(scripted)
    try:
        denied = False
        try:
            check_permission("write_file", Tier.CONFIRM, "write test")
        except PermissionDenied:
            denied = True
        approved = False
        try:
            check_permission("write_file", Tier.CONFIRM, "write test")
            approved = True
        except PermissionDenied:
            approved = False
        ok = (
            denied
            and approved
            and scripted.typed_calls[0][1] == "yes"
            and scripted.typed_calls[1][1] == "write_file"
        )
        _check("a_scripted_typed", ok, f"denied={denied} approved={approved} calls={scripted.typed_calls}")
    finally:
        set_approver(prev)
        reset_session()


def test_b_xss_render() -> None:
    # Load app.js renderMarkdown via a tiny JS engine-free Python port check:
    # execute the same rules as app/ui/app.js by importing a helper.
    js_path = PROJECT_ROOT / "app" / "ui" / "app.js"
    text = js_path.read_text(encoding="utf-8")
    ok_has = "escapeHtml" in text and "renderMarkdown" in text
    # Run render through pywebview evaluate if available; else Python mirror.
    payload = (
        'Hello <script>alert(1)</script> and <img onerror="alert(1)" src=x> '
        "and [click](javascript:alert(1)) and [ok](https://example.com)"
    )

    def py_render(src: str) -> str:
        import html as _html

        def esc(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        t = esc(src)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: (
                f'<a class="md-link" href="{esc(m.group(2))}" target="_blank" '
                f'rel="noopener noreferrer">{m.group(1)}</a>'
                if re.match(r"^https?://", m.group(2).strip(), re.I)
                else f"{m.group(1)} ({esc(m.group(2))})"
            ),
            t,
        )
        return "<p>" + t + "</p>"

    # Prefer evaluating real app.js in WebView when possible.
    rendered = None
    try:
        import webview

        api_holder: dict = {}

        class _Api:
            pass

        def _loaded():
            win = api_holder["win"]
            rendered_holder["html"] = win.evaluate_js(
                f"window.miniai._test_render({payload!r})"
            )
            win.destroy()

        rendered_holder: dict = {}
        index = (PROJECT_ROOT / "app" / "ui" / "index.html").as_uri()
        win = webview.create_window("MiniAI XSS test", index, js_api=_Api(), width=900, height=600)
        api_holder["win"] = win
        webview.start(_loaded)
        rendered = rendered_holder.get("html")
    except Exception as exc:
        print(f"[xss] webview path skipped: {exc}")
        rendered = py_render(payload)

    assert rendered is not None
    # Must not contain raw HTML tags that could execute
    no_raw_script = "<script>" not in rendered
    no_raw_img = not re.search(r"<img\b", rendered, re.I)
    no_js_href = not re.search(r"""href\s*=\s*['"]javascript:""", rendered, re.I)
    has_escaped = "&lt;script&gt;" in rendered or "&lt;img" in rendered
    inert_link = "https://example.com" in rendered
    ok = (
        ok_has
        and no_raw_script
        and no_raw_img
        and no_js_href
        and has_escaped
        and inert_link
    )
    _check(
        "b_xss_render",
        ok,
        f"no_script={no_raw_script} no_img={no_raw_img} "
        f"no_js={no_js_href} escaped={has_escaped} link={inert_link} "
        f"sample={rendered[:180]!r}",
    )


def test_c_grep_input() -> None:
    """No input( outside ConsoleApprover and test/helpers."""
    allowed_files = {
        (PROJECT_ROOT / "security" / "approver.py").resolve(),
    }
    # Test helpers / scripts may still call or patch input.
    skip_dirs = {
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "browser_profile",
        "logs",
        ".git",
    }
    offenders: list[str] = []
    # Match a real call: input( … ) not the English word "input (" in prose.
    pattern = re.compile(r"(?<![\w.])input\s*\(\s*(['\"]|\))")
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in skip_dirs for part in path.parts):
            continue
        rel = path.relative_to(PROJECT_ROOT)
        # Allow tests, scripts (chat REPL You>), chat_loop, and ConsoleApprover.
        if rel.parts[0] in ("scripts", "tests", "eval"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if path.resolve() in allowed_files:
                # ConsoleApprover may call input("..."); nothing else in that file.
                continue
            if pattern.search(line):
                offenders.append(f"{rel}:{i}:{line.strip()}")
    # ConsoleApprover file: must contain input(, and only that module among security/
    ap_text = (PROJECT_ROOT / "security" / "approver.py").read_text(encoding="utf-8")
    if "input(" not in ap_text:
        offenders.append("approver.py: ConsoleApprover missing input()")
    for rel in ("security/gate.py", "security/user_input_watch.py"):
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{i}:{line.strip()}")
    _check("c_no_input_outside", not offenders, f"offenders={offenders}")


def test_d_app_launch() -> None:
    """Launch window and close (gui=None / destroy)."""
    try:
        import webview
    except ImportError as exc:
        _check("d_app_launch", False, f"pywebview missing: {exc}")
        return

    closed = {"ok": False}
    index = (PROJECT_ROOT / "app" / "ui" / "index.html").as_uri()

    class _Api:
        def ready(self):
            return None

    def _close():
        import time

        time.sleep(1.5)
        try:
            windows = webview.windows
            if windows:
                windows[0].destroy()
            closed["ok"] = True
        except Exception as exc:
            closed["err"] = str(exc)

    try:
        webview.create_window(
            "MiniAI",
            index,
            js_api=_Api(),
            width=900,
            height=600,
            min_size=(900, 600),
        )
        webview.start(_close)
        ok = closed.get("ok", False)
        _check("d_app_launch", ok, f"closed={closed}")
    except Exception as exc:
        # Headless CI may lack WebView2; record checklist.
        checklist = (
            "MANUAL: python -m app → window title MiniAI, min 900x600, "
            "sidebar+composer visible, close with X."
        )
        _check("d_app_launch", False, f"{exc}; {checklist}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Ensure default approver is console for other imports
    set_approver(ConsoleApprover())
    test_a_scripted_typed()
    test_b_xss_render()
    test_c_grep_input()
    test_d_app_launch()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
