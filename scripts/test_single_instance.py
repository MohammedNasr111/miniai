"""Offline: single-instance mutex helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from app import single_instance as si

    check("mutex_name", si.MUTEX_NAME == "MiniAI.Desktop")
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    check("main_acquires", "acquire_single_instance" in src)
    check("main_releases", "release_single_instance" in src)

    wa = (ROOT / "app" / "webview_approver.py").read_text(encoding="utf-8")
    check("warmup_waits_idle", "Never warm while a turn" in wa or "turn still running" in wa)
    check("warmup_once", "_warmup_started" in wa)
    check("warmup_status", "Warming up…" in wa)
    check("warmup_system_tools", "system_prompt()" in wa and "active_tool_schemas()" in wa)
    check("warmup_supersede", "supersede_warmup" in wa)

    # Simulate already-held mutex → False + bring-to-front called
    with mock.patch.object(si, "sys") as msys:
        msys.platform = "win32"
        fake_kernel = mock.Mock()
        fake_kernel.CreateMutexW.return_value = 12345
        fake_kernel.GetLastError.return_value = si.ERROR_ALREADY_EXISTS
        fake_user = mock.Mock()
        fake_user.FindWindowW.return_value = 99
        fake_user.IsIconic.return_value = 1
        with mock.patch("ctypes.windll") as windll:
            windll.kernel32 = fake_kernel
            windll.user32 = fake_user
            # re-import path uses ctypes.windll in functions
            with mock.patch.object(si.ctypes, "windll", windll):
                ok = si.acquire_single_instance()
        check("second_instance_exits", ok is False)
        check("restore_called", fake_user.ShowWindow.called)

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
