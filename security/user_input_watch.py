"""Low-level mouse/keyboard watch while a desktop task grant is active.

Physical input (events without LLMHF_INJECTED / LLKHF_INJECTED) sets a
flag that desktop act tools check. Hooks run on a dedicated thread with a
message pump and are always uninstalled when the grant ends or on exit.
"""

from __future__ import annotations

import atexit
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
HC_ACTION = 0

LLMHF_INJECTED = 0x00000001
LLKHF_INJECTED = 0x00000001

ULONG_PTR = ctypes.c_size_t


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)
LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

_lock = threading.Lock()
_interrupted = False
_active = False
_thread: threading.Thread | None = None
_thread_id = 0
_mouse_hook = None
_keyboard_hook = None
_mouse_proc_ref = None
_keyboard_proc_ref = None
_atexit_registered = False


def is_interrupted() -> bool:
    with _lock:
        return _interrupted


def clear_interrupted() -> None:
    with _lock:
        global _interrupted
        _interrupted = False


def _mark_interrupted() -> None:
    with _lock:
        global _interrupted
        _interrupted = True


def handle_mouse_event(flags: int) -> None:
    """Shared logic for the mouse hook (also used by tests)."""
    if not (flags & LLMHF_INJECTED):
        _mark_interrupted()


def handle_keyboard_event(flags: int) -> None:
    """Shared logic for the keyboard hook (also used by tests)."""
    if not (flags & LLKHF_INJECTED):
        _mark_interrupted()


def _mouse_proc(n_code: int, w_param: int, l_param: int) -> int:
    if n_code == HC_ACTION and l_param:
        info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
        handle_mouse_event(int(info.flags))
    return user32.CallNextHookEx(_mouse_hook, n_code, w_param, l_param)


def _keyboard_proc(n_code: int, w_param: int, l_param: int) -> int:
    if n_code == HC_ACTION and l_param:
        info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        handle_keyboard_event(int(info.flags))
    return user32.CallNextHookEx(_keyboard_hook, n_code, w_param, l_param)


def _hook_thread_main() -> None:
    global _mouse_hook, _keyboard_hook, _mouse_proc_ref, _keyboard_proc_ref
    global _thread_id, _active

    _thread_id = kernel32.GetCurrentThreadId()
    _mouse_proc_ref = LowLevelMouseProc(_mouse_proc)
    _keyboard_proc_ref = LowLevelKeyboardProc(_keyboard_proc)
    _mouse_hook = user32.SetWindowsHookExW(
        WH_MOUSE_LL, _mouse_proc_ref, None, 0
    )
    _keyboard_hook = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _keyboard_proc_ref, None, 0
    )
    try:
        msg = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result == 0 or result == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        if _mouse_hook:
            user32.UnhookWindowsHookEx(_mouse_hook)
            _mouse_hook = None
        if _keyboard_hook:
            user32.UnhookWindowsHookEx(_keyboard_hook)
            _keyboard_hook = None
        with _lock:
            _active = False


def start_watch() -> None:
    """Install hooks while a task grant is active."""
    global _thread, _active, _atexit_registered, _interrupted
    with _lock:
        _interrupted = False
        if _active:
            return
        _active = True
    if not _atexit_registered:
        atexit.register(stop_watch)
        _atexit_registered = True
    _thread = threading.Thread(
        target=_hook_thread_main, name="miniai-input-watch", daemon=True
    )
    _thread.start()


def stop_watch() -> None:
    """Uninstall hooks and clear the interrupted flag."""
    global _thread, _thread_id, _active, _interrupted
    with _lock:
        was_active = _active
        _interrupted = False
    if not was_active and _thread is None:
        return
    tid = _thread_id
    if tid:
        user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    with _lock:
        _active = False
        _interrupted = False
        _thread = None
        _thread_id = 0


def check_continue_after_interrupt() -> bool:
    """If the user touched input, ask whether to continue the task.

    Returns True to continue (or if no interrupt). Returns False when the
    user answers no — the caller must end the task grant.
    """
    if not is_interrupted():
        return True
    print("\n[PERMISSION REQUIRED - CONFIRM]")
    print("Action: desktop_task_continue")
    print("You used the mouse or keyboard. Continue the task? (yes/no)")
    answer = input("Allow? [yes/no]: ").strip().lower()
    clear_interrupted()
    return answer == "yes"
