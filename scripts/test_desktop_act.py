"""Stage 8b/8c: desktop actions — grants, insert/replace safety, tab check.

Uses a dedicated PowerShell WinForms window (never Notepad). Every launched
process is closed in finally; the suite asserts no test windows remain.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from tests.support import answer_by_action, assert_not_real_data, use_temp_data

_TEMP_ROOT = use_temp_data()
_LOCAL = _TEMP_ROOT / "LocalAppData"
_LOCAL.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(_LOCAL)

from security.app_trust import clear_session, trusted_apps_path  # noqa: E402
from security.gate import PermissionDenied, mark_untrusted, reset_session  # noqa: E402
from security import user_input_watch  # noqa: E402
from tools.desktop import desktop_tools as dt  # noqa: E402
from tools.desktop.desktop_tools import (  # noqa: E402
    desktop_begin_task,
    desktop_insert_text,
    desktop_list_windows,
    desktop_press,
    desktop_read_window,
    desktop_set_text,
)
from tools.desktop.task_grant import (  # noqa: E402
    clear_task_grant,
    current_grant_exe,
    set_task_grant,
)
from tools.web.untrusted import BEGIN_MARKER  # noqa: E402

FAILURES: list[str] = []
_PROCS: list[subprocess.Popen] = []
FORM_TITLE = "MiniAIActTest8b"
APPLY_MARKER_FILE: Path | None = None
DELETE_MARKER_FILE: Path | None = None
SEND_MARKER_FILE: Path | None = None


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _trust_powershell() -> None:
    path = trusted_apps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"powershell.exe": true}\n', encoding="utf-8")


def _allow_act():
    return (
        patch.object(dt, "is_act_blocked", return_value=False),
        patch("tools.desktop.desktop_tools.is_act_blocked", return_value=False),
        patch(
            "tools.desktop.desktop_tools.act_blocked_message",
            return_value="blocked",
        ),
    )


def _kill_test_windows() -> None:
    try:
        import ctypes

        import uiautomation as auto

        for w in auto.GetRootControl().GetChildren():
            try:
                name = w.Name or ""
            except Exception:
                continue
            if FORM_TITLE in name or "MiniAI Modal" in name or "MiniAIReadTest" in name:
                try:
                    hwnd = w.NativeWindowHandle
                    if hwnd:
                        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                except Exception:
                    pass
    except Exception:
        pass


def _cleanup() -> None:
    clear_task_grant()
    user_input_watch.stop_watch()
    for proc in _PROCS:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
    _PROCS.clear()
    _kill_test_windows()


def _assert_proc_gone(proc: subprocess.Popen, label: str) -> None:
    try:
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    alive = proc.poll() is None
    if alive:
        FAILURES.append(f"proc-alive-{label}")
        print(f"FAIL: process still alive for {label}")


def _wait_list_contains(substr: str, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = desktop_list_windows()
        if substr.lower() in last.lower():
            return last
        time.sleep(0.3)
    return last


def _ref_for(listing: str, substr: str) -> str:
    for line in listing.splitlines():
        if substr.lower() in line.lower() and "[w" in line:
            start = line.index("[w")
            end = line.index("]", start)
            return line[start + 1 : end]
    raise AssertionError(f"No window matching {substr!r} in:\n{listing}")


def _elem_for(read_out: str, name: str) -> str:
    needle = f'"{name}"'
    for line in read_out.splitlines():
        if needle in line and "[e" in line:
            start = line.index("[e")
            end = line.index("]", start)
            return line[start + 1 : end]
    raise AssertionError(f"No element named {name!r} in:\n{read_out}")


def _elem_edit(read_out: str) -> str:
    for line in read_out.splitlines():
        if "[e" not in line or "password" in line.lower():
            continue
        if "Edit" in line or "Document" in line:
            start = line.index("[e")
            end = line.index("]", start)
            return line[start + 1 : end]
    raise AssertionError(f"No edit element in:\n{read_out}")


def _launch_winforms(initial_text: str = "") -> subprocess.Popen:
    """Dedicated multiline TextBox test window (not Notepad)."""
    global APPLY_MARKER_FILE, DELETE_MARKER_FILE, SEND_MARKER_FILE
    tmp = Path(tempfile.mkdtemp(prefix="miniai_8b_form_"))
    APPLY_MARKER_FILE = tmp / "apply.txt"
    DELETE_MARKER_FILE = tmp / "delete.txt"
    SEND_MARKER_FILE = tmp / "send.txt"
    apply_path = str(APPLY_MARKER_FILE).replace("\\", "\\\\")
    delete_path = str(DELETE_MARKER_FILE).replace("\\", "\\\\")
    send_path = str(SEND_MARKER_FILE).replace("\\", "\\\\")
    # Escape for PowerShell single-quoted here-string content via concatenation.
    init_lit = initial_text.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = '{FORM_TITLE}'
$form.Width = 480
$form.Height = 320
$tb = New-Object System.Windows.Forms.TextBox
$tb.Name = 'MainEdit'
$tb.Multiline = $true
$tb.ScrollBars = 'Vertical'
$tb.AcceptsReturn = $true
$tb.MaxLength = 0
$tb.Width = 420
$tb.Height = 120
$tb.Left = 20
$tb.Top = 20
$tb.Text = '{init_lit}'
$form.Controls.Add($tb)
$pwd = New-Object System.Windows.Forms.TextBox
$pwd.UseSystemPasswordChar = $true
$pwd.Text = 'secret-pass'
$pwd.Width = 420
$pwd.Left = 20
$pwd.Top = 150
$form.Controls.Add($pwd)
$btnApply = New-Object System.Windows.Forms.Button
$btnApply.Text = 'Apply'
$btnApply.Left = 20
$btnApply.Top = 190
$btnApply.Add_Click({{ Set-Content -Path '{apply_path}' -Value 'applied' -Encoding utf8 }})
$form.Controls.Add($btnApply)
$btnDelete = New-Object System.Windows.Forms.Button
$btnDelete.Text = 'Delete'
$btnDelete.Left = 120
$btnDelete.Top = 190
$btnDelete.Add_Click({{ Set-Content -Path '{delete_path}' -Value 'deleted' -Encoding utf8 }})
$form.Controls.Add($btnDelete)
$btnSend = New-Object System.Windows.Forms.Button
$btnSend.Text = 'Send'
$btnSend.Left = 220
$btnSend.Top = 190
$btnSend.Add_Click({{ Set-Content -Path '{send_path}' -Value 'sent' -Encoding utf8 }})
$form.Controls.Add($btnSend)
$btnTitle = New-Object System.Windows.Forms.Button
$btnTitle.Text = 'ChangeTitle'
$btnTitle.Left = 320
$btnTitle.Top = 190
$btnTitle.Add_Click({{ $form.Text = '{FORM_TITLE} - OtherDoc' }})
$form.Controls.Add($btnTitle)
$btnDialog = New-Object System.Windows.Forms.Button
$btnDialog.Text = 'Open Dialog'
$btnDialog.Left = 20
$btnDialog.Top = 230
$btnDialog.Add_Click({{
  $dlg = New-Object System.Windows.Forms.Form
  $dlg.Text = 'MiniAI Modal'
  $dlg.Width = 300
  $dlg.Height = 140
  $ok = New-Object System.Windows.Forms.Button
  $ok.Text = 'DialogOK'
  $ok.Left = 90
  $ok.Top = 40
  $ok.Add_Click({{ $dlg.Close() }})
  $dlg.Controls.Add($ok)
  $dlg.Show()
}})
$form.Controls.Add($btnDialog)
$form.Show()
while ($form.Visible) {{
  [System.Windows.Forms.Application]::DoEvents()
  Start-Sleep -Milliseconds 150
}}
"""
    proc = subprocess.Popen(
        [
            "powershell",
            "-STA",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _PROCS.append(proc)
    return proc


def test_1_no_grant() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms("hello")
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action({"desktop_read_window": "session"}):
                read = desktop_read_window(wref)
                eref = _elem_edit(read)
                with answer_by_action(
                    {"desktop_press": "SHOULD_NOT", "desktop_set_text": "SHOULD_NOT"},
                    default="no",
                ) as log:
                    out_p = desktop_press(eref)
                    out_s = desktop_set_text(eref, "x")
                    prompts = list(log)
            ok = (
                "Call desktop_begin_task first" in out_p
                and "Call desktop_begin_task first" in out_s
                and len(prompts) == 0
            )
            report("1", ok, f"press={out_p!r} set={out_s!r} prompts={len(prompts)}")
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test1")


def test_2_grant_set_text_and_apply() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms("")
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "type into field")
                read = desktop_read_window(wref)
                eref = _elem_edit(read)
                out = desktop_set_text(eref, "Meeting notes from MiniAI")
                apply_ref = _elem_for(read, "Apply")
                # Re-read after set so snapshots stay valid
                read2 = desktop_read_window(wref)
                apply_ref = _elem_for(read2, "Apply")
                with answer_by_action({"desktop_press": "SHOULD_NOT"}, default="no") as log:
                    desktop_press(apply_ref)
                    prompts = list(log)
            time.sleep(0.4)
            apply_ok = APPLY_MARKER_FILE is not None and APPLY_MARKER_FILE.exists()
            ok = "Meeting notes from MiniAI" in out and apply_ok and len(prompts) == 0
            report(
                "2",
                ok,
                f"text_ok={'Meeting notes from MiniAI' in out} apply={apply_ok} "
                f"prompts={len(prompts)}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test2")


def test_3_delete_send_prompt() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms()
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "dangerous buttons")
                read = desktop_read_window(wref)
                delete_ref = _elem_for(read, "Delete")
                send_ref = _elem_for(read, "Send")
                out_d = out_s = ""
                with answer_by_action({"desktop_press": "no"}, default="no") as log:
                    try:
                        out_d = desktop_press(delete_ref)
                    except PermissionDenied as exc:
                        out_d = str(exc)
                    try:
                        out_s = desktop_press(send_ref)
                    except PermissionDenied as exc:
                        out_s = str(exc)
                    prompts = list(log)
            time.sleep(0.3)
            no_delete = DELETE_MARKER_FILE is not None and not DELETE_MARKER_FILE.exists()
            no_send = SEND_MARKER_FILE is not None and not SEND_MARKER_FILE.exists()
            ok = no_delete and no_send and len(prompts) >= 2
            report(
                "3",
                ok,
                f"no_delete={no_delete} no_send={no_send} prompts={len(prompts)} "
                f"out_d={out_d[:80]!r}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test3")


def test_4_dialog_prompt() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms()
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {
                    "desktop_begin_task": "yes",
                    "desktop_read_window": "session",
                    "desktop_press": "yes",
                }
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "open dialog")
                read = desktop_read_window(wref)
                open_ref = _elem_for(read, "Open Dialog")
                out_open = desktop_press(open_ref)
                time.sleep(1.0)
                listing2 = ""
                ok_ref = ""
                for _ in range(10):
                    listing2 = desktop_list_windows()
                    if "MiniAI Modal" in listing2:
                        mref = _ref_for(listing2, "MiniAI Modal")
                        set_task_grant("powershell.exe", "dialog", mref)
                        read_m = desktop_read_window(mref)
                        if "DialogOK" in read_m:
                            ok_ref = _elem_for(read_m, "DialogOK")
                            break
                    time.sleep(0.3)
                prompts: list = []
                if ok_ref:
                    with answer_by_action({"desktop_press": "no"}, default="no") as log:
                        try:
                            desktop_press(ok_ref)
                        except PermissionDenied:
                            pass
                        prompts = list(log)
            ok = bool(ok_ref) and len(prompts) >= 1
            report(
                "4",
                ok,
                f"prompts={len(prompts)} ok_ref={ok_ref!r} open={out_open[:60]!r} "
                f"has_modal={'MiniAI Modal' in listing2}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test4")


def test_5_password_set_refused() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms()
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "password")
                read = desktop_read_window(wref)
                pref = None
                for line in read.splitlines():
                    if "password field - not read" in line and "[e" in line:
                        start = line.index("[e")
                        end = line.index("]", start)
                        pref = line[start + 1 : end]
                        break
                assert pref is not None
                out = desktop_set_text(pref, "hack")
            ok = "password" in out.lower() and "Refused" in out
            report("5", ok, f"out={out!r}")
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test5")


def test_6_changed_element() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms()
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "rename")
                read = desktop_read_window(wref)
                apply_ref = _elem_for(read, "Apply")
                snap = dt._last_elements[apply_ref]
                snap["name"] = "RenamedApply"
                out = desktop_press(apply_ref)
            ok = "The window changed; read it again" in out
            report("6", ok, f"out={out!r}")
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test6")


def test_7_act_blocked_apps() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms("x")
    try:
        listing = _wait_list_contains(FORM_TITLE)
        wref = _ref_for(listing, FORM_TITLE)
        with answer_by_action(
            {"desktop_read_window": "session", "desktop_begin_task": "yes"}
        ):
            desktop_read_window(wref)
            with patch.object(dt, "exe_for_hwnd", return_value="chrome.exe"), patch(
                "tools.desktop.desktop_tools.exe_for_hwnd", return_value="chrome.exe"
            ):
                out_begin = desktop_begin_task(wref, "nope")
            with patch.object(dt, "exe_for_hwnd", return_value="explorer.exe"), patch(
                "tools.desktop.desktop_tools.exe_for_hwnd", return_value="explorer.exe"
            ):
                out_exp = desktop_begin_task(wref, "nope")
        ok = "browser tools" in out_begin.lower() and "file tools" in out_exp.lower()
        report("7", ok, f"chrome={out_begin!r} explorer={out_exp!r}")
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test7")


def test_8_grant_expires() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms("abc")
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                read = desktop_read_window(wref)
                desktop_begin_task(wref, "temp grant")
                eref = _elem_edit(read)
                assert current_grant_exe() == "powershell.exe"
            clear_task_grant()
            out = desktop_press(eref)
            ok = "Call desktop_begin_task first" in out and current_grant_exe() is None
            report("8", ok, f"out={out!r}")
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test8")


def test_9_emergency_stop() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms("stop")
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                read = desktop_read_window(wref)
                desktop_begin_task(wref, "interrupt test")
                eref = _elem_edit(read)
                user_input_watch.handle_mouse_event(user_input_watch.LLMHF_INJECTED)
                assert not user_input_watch.is_interrupted()
                user_input_watch.handle_mouse_event(0)
                assert user_input_watch.is_interrupted()
                with answer_by_action(
                    {"desktop_task_continue": "no"}, default="no"
                ) as log:
                    out = desktop_set_text(eref, "should not apply")
                    prompts = list(log)
            ok = (
                current_grant_exe() is None
                and "chose not to continue" in out.lower()
                and len(prompts) == 1
                and "should not apply" not in out
            )
            report(
                "9",
                ok,
                f"out={out!r} prompts={len(prompts)} grant={current_grant_exe()}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test9")


def test_10_tainted_begin_typed() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    mark_untrusted("web_research")
    proc = _launch_winforms("taint")
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            denied = False
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"},
                default="no",
            ):
                try:
                    desktop_begin_task(wref, "typed required")
                except PermissionDenied:
                    denied = True
            ok_denied = denied and current_grant_exe() is None
            with answer_by_action(
                {
                    "desktop_begin_task": "desktop_begin_task",
                    "desktop_read_window": "session",
                }
            ) as log_ok:
                out_ok = desktop_begin_task(wref, "typed required")
                prompts_ok = list(log_ok)
            ok = (
                ok_denied
                and current_grant_exe() == "powershell.exe"
                and BEGIN_MARKER in out_ok
                and any(p[2] == "desktop_begin_task" for p in prompts_ok)
            )
            report(
                "10",
                ok,
                f"denied={denied} grant={current_grant_exe()} typed={prompts_ok!r}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test10")


def test_a_insert_preserves_long_text() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    original = ("ABCDEFGHIJ" * 1000)  # 10,000 chars
    assert len(original) == 10000
    insert = "HEAD-"
    proc = _launch_winforms(original)
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "insert start")
                read = desktop_read_window(wref)
                eref = _elem_edit(read)
                out = desktop_insert_text(eref, insert, position="start")
                # Full value (Win32/ValuePattern), not the 3000-char observation
                snap = dt._last_elements[eref]
                pattern = dt._get_value_pattern(snap["control"])
                value = dt._full_edit_value(snap["control"], pattern)
            intended = insert + original
            ok = (
                value == intended
                and original in value
                and value.startswith(insert)
                and "Insert failed" not in out
            )
            report(
                "a",
                ok,
                f"len={len(value)} want={len(intended)} starts={value.startswith(insert)}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test_a")


def test_b_set_text_prompt_on_nonempty() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    existing = "keep-me-please"
    proc = _launch_winforms(existing)
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "replace?")
                read = desktop_read_window(wref)
                eref = _elem_edit(read)
                denied = False
                with answer_by_action({"desktop_set_text": "no"}, default="no") as log:
                    try:
                        desktop_set_text(eref, "NEW")
                    except PermissionDenied:
                        denied = True
                    prompts = list(log)
                snap = dt._last_elements[eref]
                pattern = dt._get_value_pattern(snap["control"])
                value = str(pattern.Value or "")
            desc = prompts[0][1] if prompts else ""
            # description is in print before input; capture from prompt log action
            # Re-run capture of printed description via check that prompt happened
            # with both counts — read from the PermissionDenied path's printed text
            # by checking log length and that value unchanged.
            ok = (
                denied
                and value == existing
                and len(prompts) == 1
            )
            # Also verify counts appear when we answer yes path description:
            # call check by inspecting printed description through a yes that we deny
            # after capturing — use a second field read of the prompt text from
            # answer_by_action which stores the input prompt only. Capture print via
            # another call that records description through gate.
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                if current_grant_exe() is None:
                    desktop_begin_task(wref, "replace2")
                read = desktop_read_window(wref)
                eref = _elem_edit(read)
            captured: list[str] = []
            real_print = print

            def capturing_print(*args, **kwargs):
                text = kwargs.get("sep", " ").join(str(a) for a in args)
                captured.append(text)
                return real_print(*args, **kwargs)

            import builtins

            with patch("builtins.print", side_effect=capturing_print), answer_by_action(
                {"desktop_set_text": "no"}, default="no"
            ):
                try:
                    desktop_set_text(eref, "ABCDEFGHIJ")  # 10 chars
                except PermissionDenied:
                    pass
            joined = "\n".join(captured)
            has_counts = (
                f"{len(existing)} characters" in joined
                and "10 characters" in joined
                and "Replace the existing text" in joined
            )
            ok = ok and has_counts
            report(
                "b",
                ok,
                f"denied={denied} unchanged={value == existing} has_counts={has_counts}",
            )
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test_b")


def test_c_title_changed_refused() -> None:
    import ctypes

    reset_session()
    clear_session()
    clear_task_grant()
    _trust_powershell()
    proc = _launch_winforms("title-check")
    try:
        p1, p2, p3 = _allow_act()
        with p1, p2, p3:
            listing = _wait_list_contains(FORM_TITLE)
            wref = _ref_for(listing, FORM_TITLE)
            with answer_by_action(
                {"desktop_begin_task": "yes", "desktop_read_window": "session"}
            ):
                desktop_read_window(wref)
                desktop_begin_task(wref, "title change")
                read = desktop_read_window(wref)
                eref = _elem_edit(read)
                # Change title outside MiniAI so the stored read title is stale
                # (a press would re-read and refresh the snapshot).
                hwnd = dt._last_read_hwnd
                assert hwnd
                ctypes.windll.user32.SetWindowTextW(
                    hwnd, f"{FORM_TITLE} - OtherDoc"
                )
                time.sleep(0.2)
                out = desktop_set_text(eref, "nope")
            ok = "different document or tab" in out and "title changed" in out
            report("c", ok, f"out={out!r}")
    finally:
        proc.kill()
        _assert_proc_gone(proc, "test_c")


def _assert_no_test_windows_left() -> None:
    listing = desktop_list_windows()
    leftover = FORM_TITLE in listing or "MiniAI Modal" in listing or "MiniAIReadTest" in listing
    report("cleanup-windows", not leftover, f"leftover={leftover} listing_snip={listing[:200]!r}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    assert_not_real_data()
    print(f"trusted_apps_path={trusted_apps_path()}")
    try:
        test_1_no_grant()
        test_2_grant_set_text_and_apply()
        test_3_delete_send_prompt()
        test_4_dialog_prompt()
        test_5_password_set_refused()
        test_6_changed_element()
        test_7_act_blocked_apps()
        test_8_grant_expires()
        test_9_emergency_stop()
        test_10_tainted_begin_typed()
        test_a_insert_preserves_long_text()
        test_b_set_text_prompt_on_nonempty()
        test_c_title_changed_refused()
    finally:
        _cleanup()
        time.sleep(0.5)
        _assert_no_test_windows_left()
    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    raise SystemExit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
