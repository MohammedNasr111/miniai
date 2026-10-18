"""Stage 8b: desktop actions — grants, always-ask, emergency stop."""

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
from security.gate import mark_untrusted, reset_session  # noqa: E402
from security import user_input_watch  # noqa: E402
from tools.desktop import desktop_tools as dt  # noqa: E402
from tools.desktop.desktop_tools import (  # noqa: E402
    desktop_begin_task,
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
NOTEPAD_MARKER = "miniai_8b_notepad_"
APPLY_MARKER_FILE: Path | None = None
DELETE_MARKER_FILE: Path | None = None
SEND_MARKER_FILE: Path | None = None


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


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
    try:
        import ctypes

        import uiautomation as auto

        for w in auto.GetRootControl().GetChildren():
            try:
                name = w.Name or ""
            except Exception:
                continue
            if FORM_TITLE in name or NOTEPAD_MARKER in name:
                try:
                    hwnd = w.NativeWindowHandle
                    if hwnd:
                        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                except Exception:
                    pass
    except Exception:
        pass


def _trust_notepad() -> None:
    path = trusted_apps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data["notepad.exe"] = True
    data["powershell.exe"] = True  # for WinForms host read
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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


def _launch_winforms() -> subprocess.Popen:
    global APPLY_MARKER_FILE, DELETE_MARKER_FILE, SEND_MARKER_FILE
    tmp = Path(tempfile.mkdtemp(prefix="miniai_8b_form_"))
    APPLY_MARKER_FILE = tmp / "apply.txt"
    DELETE_MARKER_FILE = tmp / "delete.txt"
    SEND_MARKER_FILE = tmp / "send.txt"
    apply_path = str(APPLY_MARKER_FILE).replace("\\", "\\\\")
    delete_path = str(DELETE_MARKER_FILE).replace("\\", "\\\\")
    send_path = str(SEND_MARKER_FILE).replace("\\", "\\\\")
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = '{FORM_TITLE}'
$form.Width = 420
$form.Height = 260
$tb = New-Object System.Windows.Forms.TextBox
$tb.Name = 'MainEdit'
$tb.Width = 360
$tb.Left = 20
$tb.Top = 20
$form.Controls.Add($tb)
$pwd = New-Object System.Windows.Forms.TextBox
$pwd.UseSystemPasswordChar = $true
$pwd.Text = 'secret-pass'
$pwd.Width = 360
$pwd.Left = 20
$pwd.Top = 50
$form.Controls.Add($pwd)
$btnApply = New-Object System.Windows.Forms.Button
$btnApply.Text = 'Apply'
$btnApply.Left = 20
$btnApply.Top = 90
$btnApply.Add_Click({{ Set-Content -Path '{apply_path}' -Value 'applied' -Encoding utf8 }})
$form.Controls.Add($btnApply)
$btnDelete = New-Object System.Windows.Forms.Button
$btnDelete.Text = 'Delete'
$btnDelete.Left = 120
$btnDelete.Top = 90
$btnDelete.Add_Click({{ Set-Content -Path '{delete_path}' -Value 'deleted' -Encoding utf8 }})
$form.Controls.Add($btnDelete)
$btnSend = New-Object System.Windows.Forms.Button
$btnSend.Text = 'Send'
$btnSend.Left = 220
$btnSend.Top = 90
$btnSend.Add_Click({{ Set-Content -Path '{send_path}' -Value 'sent' -Encoding utf8 }})
$form.Controls.Add($btnSend)
$btnDialog = New-Object System.Windows.Forms.Button
$btnDialog.Text = 'Open Dialog'
$btnDialog.Left = 20
$btnDialog.Top = 130
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
  # Top-level Show (no Owner) so EnumWindows lists it; title has Modal.
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


def _open_notepad(text: str = "") -> tuple[subprocess.Popen, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="miniai_8b_np_"))
    path = tmp / f"{NOTEPAD_MARKER}note.txt"
    path.write_text(text, encoding="utf-8")
    proc = subprocess.Popen(["notepad.exe", str(path)])
    _PROCS.append(proc)
    return proc, path


def test_1_no_grant() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    proc, _path = _open_notepad("hello\n")
    listing = _wait_list_contains(NOTEPAD_MARKER)
    wref = _ref_for(listing, NOTEPAD_MARKER)
    with answer_by_action({"desktop_read_window": "session", "desktop_press": "yes"}):
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
    proc.kill()


def test_2_grant_set_text_and_apply() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    # Notepad set_text
    proc_np, _path = _open_notepad("")
    listing = _wait_list_contains(NOTEPAD_MARKER)
    wref = _ref_for(listing, NOTEPAD_MARKER)
    with answer_by_action(
        {
            "desktop_begin_task": "yes",
            "desktop_read_window": "session",
        }
    ):
        desktop_read_window(wref)
        desktop_begin_task(wref, "type into notepad")
        # Re-read after begin (grant active)
        read = desktop_read_window(wref)
        eref = _elem_edit(read)
        out = desktop_set_text(eref, "Meeting notes from MiniAI")
    ok_np = "Meeting notes from MiniAI" in out
    # WinForms Apply
    _launch_winforms()
    listing2 = _wait_list_contains(FORM_TITLE)
    wref2 = _ref_for(listing2, FORM_TITLE)
    # powershell is act-blocked! Apply test must use a non-blocked host.
    # WinForms runs under powershell.exe which is ACT_BLOCKED.
    # For Apply we need an app that isn't act-blocked. Use notepad for
    # set_text only in this test, and for Apply use a custom approach:
    # patch is_act_blocked to allow powershell for the form tests.
    report("2a-notepad-set", ok_np, f"out_has_text={ok_np}")

    with patch.object(dt, "is_act_blocked", return_value=False), patch(
        "tools.desktop.desktop_tools.is_act_blocked", return_value=False
    ), patch(
        "tools.desktop.desktop_tools.act_blocked_message",
        return_value="blocked",
    ):
        clear_task_grant()
        with answer_by_action({"desktop_begin_task": "yes", "desktop_read_window": "session"}):
            read2 = desktop_read_window(wref2)
            desktop_begin_task(wref2, "press Apply")
            read2 = desktop_read_window(wref2)
            apply_ref = _elem_for(read2, "Apply")
            with answer_by_action({"desktop_press": "SHOULD_NOT"}, default="no") as log:
                desktop_press(apply_ref)
                prompts = list(log)
        time.sleep(0.5)
        apply_ok = APPLY_MARKER_FILE is not None and APPLY_MARKER_FILE.exists()
        ok_apply = apply_ok and len(prompts) == 0
    report("2", ok_np and ok_apply, f"notepad={ok_np} apply_file={apply_ok} prompts={len(prompts)}")
    try:
        proc_np.kill()
    except OSError:
        pass


def test_3_delete_send_prompt() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    _launch_winforms()
    listing = _wait_list_contains(FORM_TITLE)
    wref = _ref_for(listing, FORM_TITLE)
    with patch.object(dt, "is_act_blocked", return_value=False), patch(
        "tools.desktop.desktop_tools.is_act_blocked", return_value=False
    ):
        with answer_by_action({"desktop_begin_task": "yes", "desktop_read_window": "session"}):
            desktop_read_window(wref)
            desktop_begin_task(wref, "dangerous buttons")
            read = desktop_read_window(wref)
            delete_ref = _elem_for(read, "Delete")
            send_ref = _elem_for(read, "Send")
            from security.gate import PermissionDenied

            prompts: list = []
            out_d = ""
            out_s = ""
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


def test_4_dialog_prompt() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    _launch_winforms()
    listing = _wait_list_contains(FORM_TITLE)
    wref = _ref_for(listing, FORM_TITLE)
    with patch.object(dt, "is_act_blocked", return_value=False), patch(
        "tools.desktop.desktop_tools.is_act_blocked", return_value=False
    ):
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
            read_m = ""
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
            from security.gate import PermissionDenied

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


def test_5_password_set_refused() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    _launch_winforms()
    listing = _wait_list_contains(FORM_TITLE)
    wref = _ref_for(listing, FORM_TITLE)
    with patch.object(dt, "is_act_blocked", return_value=False), patch(
        "tools.desktop.desktop_tools.is_act_blocked", return_value=False
    ):
        with answer_by_action({"desktop_begin_task": "yes", "desktop_read_window": "session"}):
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


def test_6_changed_element() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    _launch_winforms()
    listing = _wait_list_contains(FORM_TITLE)
    wref = _ref_for(listing, FORM_TITLE)
    with patch.object(dt, "is_act_blocked", return_value=False), patch(
        "tools.desktop.desktop_tools.is_act_blocked", return_value=False
    ):
        with answer_by_action({"desktop_begin_task": "yes", "desktop_read_window": "session"}):
            desktop_read_window(wref)
            desktop_begin_task(wref, "rename")
            read = desktop_read_window(wref)
            apply_ref = _elem_for(read, "Apply")
            snap = dt._last_elements[apply_ref]
            # Mutate stored snapshot name so re-verify fails
            snap["name"] = "RenamedApply"
            out = desktop_press(apply_ref)
    ok = "The window changed; read it again" in out
    report("6", ok, f"out={out!r}")


def test_7_act_blocked_apps() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    # Fake explorer / chrome window refs by patching resolve
    listing = desktop_list_windows()
    # Use a real window but patch exe to chrome/explorer at act time
    _trust_notepad()
    proc, _ = _open_notepad("x\n")
    listing = _wait_list_contains(NOTEPAD_MARKER)
    wref = _ref_for(listing, NOTEPAD_MARKER)
    with answer_by_action({"desktop_read_window": "session", "desktop_begin_task": "yes"}):
        desktop_read_window(wref)
        with patch.object(dt, "exe_for_hwnd", return_value="chrome.exe"), patch(
            "tools.desktop.desktop_tools.exe_for_hwnd", return_value="chrome.exe"
        ):
            # begin_task sees chrome via resolve
            out_begin = desktop_begin_task(wref, "nope")
        with patch.object(dt, "exe_for_hwnd", return_value="explorer.exe"), patch(
            "tools.desktop.desktop_tools.exe_for_hwnd", return_value="explorer.exe"
        ):
            out_exp = desktop_begin_task(wref, "nope")
    ok = (
        "browser tools" in out_begin.lower()
        and "file tools" in out_exp.lower()
    )
    report("7", ok, f"chrome={out_begin!r} explorer={out_exp!r}")
    proc.kill()


def test_8_grant_expires() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    proc, _ = _open_notepad("abc\n")
    listing = _wait_list_contains(NOTEPAD_MARKER)
    wref = _ref_for(listing, NOTEPAD_MARKER)
    with answer_by_action({"desktop_begin_task": "yes", "desktop_read_window": "session"}):
        read = desktop_read_window(wref)
        desktop_begin_task(wref, "temp grant")
        eref = _elem_edit(read)
        assert current_grant_exe() == "notepad.exe"
    # Simulate end of turn
    clear_task_grant()
    out = desktop_press(eref)
    ok = "Call desktop_begin_task first" in out and current_grant_exe() is None
    report("8", ok, f"out={out!r}")
    proc.kill()


def test_9_emergency_stop() -> None:
    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    proc, _ = _open_notepad("stop\n")
    listing = _wait_list_contains(NOTEPAD_MARKER)
    wref = _ref_for(listing, NOTEPAD_MARKER)
    with answer_by_action({"desktop_begin_task": "yes", "desktop_read_window": "session"}):
        read = desktop_read_window(wref)
        desktop_begin_task(wref, "interrupt test")
        eref = _elem_edit(read)
        # Injected event must NOT trigger
        user_input_watch.handle_mouse_event(user_input_watch.LLMHF_INJECTED)
        assert not user_input_watch.is_interrupted()
        # Physical (non-injected) event triggers
        user_input_watch.handle_mouse_event(0)
        assert user_input_watch.is_interrupted()
        with answer_by_action({"desktop_task_continue": "no"}, default="no") as log:
            out = desktop_set_text(eref, "should not apply")
            prompts = list(log)
    ok = (
        current_grant_exe() is None
        and "chose not to continue" in out.lower()
        and len(prompts) == 1
        and "should not apply" not in out
    )
    report("9", ok, f"out={out!r} prompts={len(prompts)} grant={current_grant_exe()}")
    proc.kill()


def test_10_tainted_begin_typed() -> None:
    from security.gate import PermissionDenied

    reset_session()
    clear_session()
    clear_task_grant()
    _trust_notepad()
    mark_untrusted("web_research")
    proc, _ = _open_notepad("taint\n")
    listing = _wait_list_contains(NOTEPAD_MARKER)
    wref = _ref_for(listing, NOTEPAD_MARKER)
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
        {"desktop_begin_task": "desktop_begin_task", "desktop_read_window": "session"}
    ) as log_ok:
        out_ok = desktop_begin_task(wref, "typed required")
        prompts_ok = list(log_ok)
    ok = (
        ok_denied
        and current_grant_exe() == "notepad.exe"
        and BEGIN_MARKER in out_ok
        and any(p[2] == "desktop_begin_task" for p in prompts_ok)
    )
    report(
        "10",
        ok,
        f"denied={denied} grant={current_grant_exe()} typed_answers={prompts_ok!r}",
    )
    proc.kill()


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
    finally:
        _cleanup()
    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    raise SystemExit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
