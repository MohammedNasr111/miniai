"""Offline + live checks: hidden subprocess kwargs, firewall cache, no console flash."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def test_hidden_kwargs() -> None:
    from config.proc import hidden_subprocess_kwargs

    if sys.platform != "win32":
        kw = hidden_subprocess_kwargs()
        _check("hidden_empty_nonwin", kw == {}, f"got={kw!r}")
        return

    kw = hidden_subprocess_kwargs()
    _check(
        "hidden_create_no_window",
        kw.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
        == subprocess.CREATE_NO_WINDOW,
        f"flags={kw.get('creationflags')!r}",
    )
    si = kw.get("startupinfo")
    _check(
        "hidden_startupinfo",
        si is not None
        and (si.dwFlags & subprocess.STARTF_USESHOWWINDOW)
        and si.wShowWindow == subprocess.SW_HIDE,
        f"si={si!r} dwFlags={getattr(si, 'dwFlags', None)!r}",
    )

    existing = 0x00000004  # CREATE_SUSPENDED-like bit for OR test
    kw2 = hidden_subprocess_kwargs(creationflags=existing)
    flags = kw2.get("creationflags", 0)
    _check(
        "hidden_or_flags",
        (flags & subprocess.CREATE_NO_WINDOW) == subprocess.CREATE_NO_WINDOW
        and (flags & existing) == existing,
        f"flags={flags!r} expected OR of CREATE_NO_WINDOW|{existing}",
    )


def test_firewall_cache_push_status() -> None:
    from app.webview_approver import AppBridge
    from tools.code import runner as runner_mod

    runner_mod.clear_firewall_status_cache()
    calls = {"n": 0}

    def fake_uncached() -> str:
        calls["n"] += 1
        return "INSTALLED"

    mono = {"t": 1000.0}

    bridge = AppBridge()
    # Avoid real JS / network in status push.
    bridge._call_js = lambda *a, **k: None  # type: ignore[method-assign]
    with patch.object(runner_mod, "_firewall_rule_status_uncached", side_effect=fake_uncached):
        with patch.object(runner_mod.time, "monotonic", side_effect=lambda: mono["t"]):
            for _ in range(30):
                bridge.push_status()
                mono["t"] += 1.0  # 30 seconds total; well under 300s TTL
    _check(
        "push_status_fw_at_most_once",
        calls["n"] <= 1,
        f"uncached_calls={calls['n']} (expected <=1 over 30 push_status)",
    )
    runner_mod.clear_firewall_status_cache()


# --- live: pythonw console flash ---------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.restype = ctypes.c_bool
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

CONSOLE_EXES = {
    "conhost.exe",
    "windowsterminal.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
}
CONSOLE_CLASSES = {
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
}


def _exe_name(pid: int) -> str:
    try:
        import psutil

        return Path(psutil.Process(pid).exe()).name.lower()
    except Exception:
        return ""


def _descendant_pids(root: int) -> set[int]:
    try:
        import psutil

        root_p = psutil.Process(root)
        out = {root}
        for child in root_p.children(recursive=True):
            out.add(child.pid)
        return out
    except Exception:
        return {root}


def _enum_console_hwnds() -> dict[int, tuple[str, int]]:
    """hwnd -> (class_name, pid) for visible console-like top-level windows."""
    found: dict[int, tuple[str, int]] = {}

    @WNDENUMPROC
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _exe_name(int(pid.value))
        if cls in CONSOLE_CLASSES or exe in CONSOLE_EXES:
            found[int(hwnd)] = (cls, int(pid.value))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def test_live_pythonw_no_console() -> None:
    if sys.platform != "win32":
        print("SKIP: live_pythonw (not Windows)")
        return

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        # venv may only have python.exe; try Scripts/pythonw.exe next to it
        alt = Path(sys.executable).parent / "pythonw.exe"
        pythonw = alt if alt.is_file() else pythonw
    if not pythonw.is_file():
        _check("live_pythonw_exists", False, f"pythonw not found near {sys.executable}")
        return

    before = _enum_console_hwnds()
    proc = subprocess.Popen(
        [str(pythonw), "-m", "app"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **__import__("config.proc", fromlist=["hidden_subprocess_kwargs"]).hidden_subprocess_kwargs(),
    )
    try:
        time.sleep(60.0)
        after = _enum_console_hwnds()
        tree = _descendant_pids(proc.pid)
        new_hits = []
        for hwnd, (cls, pid) in after.items():
            if hwnd in before:
                continue
            if pid in tree or _exe_name(pid) in CONSOLE_EXES:
                # Only count if owned by our app tree, or a new console whose
                # parent is in our tree.
                try:
                    import psutil

                    parent = psutil.Process(pid).ppid()
                except Exception:
                    parent = -1
                if pid in tree or parent in tree:
                    new_hits.append((hwnd, cls, pid, _exe_name(pid)))
        _check(
            "live_pythonw_no_new_console",
            len(new_hits) == 0,
            f"new_console_windows={new_hits!r} app_pid={proc.pid}",
        )
    finally:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception as exc:
            print(f"WARN: failed to close app: {exc}")


def main() -> int:
    test_hidden_kwargs()
    test_firewall_cache_push_status()
    if "--live" in sys.argv:
        test_live_pythonw_no_console()
    else:
        print("SKIP: live_pythonw (pass --live to run)")
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
