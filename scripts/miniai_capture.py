"""Capture ONLY the MiniAI HWND (never whatever happens to be in front).

Round 8e: ImageGrab of a screen rect captured Claude when it was foreground.
This helper requires title == \"MiniAI\" and GetForegroundWindow() == hwnd,
then grabs via PrintWindow (window's own bits) with a verified-foreground
BitBlt/ImageGrab fallback. On any failure: print CAPTURE_ERR=… and return
False without writing a file.
"""

from __future__ import annotations

import ctypes
import hashlib
import time
from ctypes import wintypes
from pathlib import Path
from typing import Optional

EXPECTED_TITLE = "MiniAI"
PW_CLIENTONLY = 1
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SW_RESTORE = 9

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_uint]
user32.PrintWindow.restype = wintypes.BOOL
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.GetWindowDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_uint,
]
gdi32.GetDIBits.restype = ctypes.c_int


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value or ""


def find_miniai_hwnd() -> int:
    hwnd = user32.FindWindowW(None, EXPECTED_TITLE)
    return int(hwnd) if hwnd else 0


def _force_foreground(hwnd: int) -> None:
    """Best-effort focus steal so GetForegroundWindow can match hwnd."""
    hwnd = int(hwnd)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    try:
        user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
    except Exception:
        pass
    fg = int(user32.GetForegroundWindow() or 0)
    cur_tid = int(kernel32.GetCurrentThreadId())
    fg_tid = int(user32.GetWindowThreadProcessId(fg, None)) if fg else 0
    target_tid = int(user32.GetWindowThreadProcessId(hwnd, None))
    attached_fg = False
    attached_tg = False
    try:
        if fg_tid and fg_tid != cur_tid:
            attached_fg = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        if target_tid and target_tid != cur_tid and target_tid != fg_tid:
            attached_tg = bool(user32.AttachThreadInput(cur_tid, target_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
        user32.SetForegroundWindow(hwnd)
        user32.SetWindowPos(
            hwnd,
            HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
    finally:
        if attached_tg:
            user32.AttachThreadInput(cur_tid, target_tid, False)
        if attached_fg:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


def assert_miniai_foreground(hwnd: int) -> tuple[bool, str]:
    """Return (ok, err). Requires title MiniAI and foreground == hwnd."""
    if not hwnd:
        return False, "no hwnd"
    title = window_title(hwnd)
    if title != EXPECTED_TITLE:
        return False, f"title={title!r}"
    _force_foreground(hwnd)
    time.sleep(0.25)
    fg = int(user32.GetForegroundWindow() or 0)
    if fg != int(hwnd):
        _force_foreground(hwnd)
        time.sleep(0.4)
        fg = int(user32.GetForegroundWindow() or 0)
    if fg != int(hwnd):
        return False, f"foreground={fg} want={int(hwnd)}"
    # Re-check title after focus (another window must not have stolen the title match).
    if window_title(hwnd) != EXPECTED_TITLE:
        return False, f"title-after={window_title(hwnd)!r}"
    return True, ""


def _dib_to_image(hdc: int, hbmp: int, width: int, height: int):
    from PIL import Image

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(width * height * 4)
    got = gdi32.GetDIBits(
        hdc,
        hbmp,
        0,
        height,
        buf,
        ctypes.byref(bmi),
        0,  # DIB_RGB_COLORS
    )
    if not got:
        return None
    # BGRA -> RGB
    img = Image.frombuffer("RGBA", (width, height), bytes(buf), "raw", "BGRA", 0, 1)
    return img.convert("RGB")


def _printwindow_capture(hwnd: int, width: int, height: int):
    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bmp)
    img = None
    try:
        ok = bool(user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT))
        if not ok:
            ok = bool(user32.PrintWindow(hwnd, mem_dc, 0))
        if not ok:
            # BitBlt the window DC into the memory DC (window's own area).
            ok = bool(
                gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY)
            )
        if ok:
            img = _dib_to_image(mem_dc, bmp, width, height)
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd, hwnd_dc)
    return img


def _verified_grab_fallback(hwnd: int, rect: wintypes.RECT):
    """Last resort: screen crop only after foreground == hwnd is confirmed again."""
    from PIL import ImageGrab

    ok, err = assert_miniai_foreground(hwnd)
    if not ok:
        return None, err
    box = (rect.left, rect.top, rect.right, rect.bottom)
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
    except TypeError:
        img = ImageGrab.grab(bbox=box)
    return img, ""


def capture_miniai_window(path: Path | str, *, hwnd: Optional[int] = None) -> bool:
    """Save a PNG of the MiniAI window only. Never writes on failure."""
    path = Path(path)
    target = int(hwnd) if hwnd else find_miniai_hwnd()
    if not target:
        print("CAPTURE_ERR=no hwnd", path.name)
        return False
    ok, err = assert_miniai_foreground(target)
    if not ok:
        print(f"CAPTURE_ERR={err}", path.name)
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(target, ctypes.byref(rect)):
        print("CAPTURE_ERR=GetWindowRect", path.name)
        return False
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 32 or height < 32:
        print(f"CAPTURE_ERR=size {width}x{height}", path.name)
        return False

    img = _printwindow_capture(target, width, height)
    used_printwindow = img is not None
    if img is None:
        img, err2 = _verified_grab_fallback(target, rect)
        if img is None:
            print(f"CAPTURE_ERR=grab {err2}", path.name)
            return False

    # Final gate before disk: title must still be MiniAI. If we had to use a
    # screen-crop fallback, also re-require foreground == hwnd (crop is unsafe
    # otherwise). PrintWindow already copied this HWND's own bits.
    if window_title(target) != EXPECTED_TITLE:
        print(f"CAPTURE_ERR=pre-save title={window_title(target)!r}", path.name)
        return False
    if not used_printwindow:
        ok, err = assert_miniai_foreground(target)
        if not ok:
            print(f"CAPTURE_ERR=pre-save {err}", path.name)
            return False

    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep a real image suffix so PIL accepts the temp path.
    tmp = path.with_name(path.stem + ".__miniai_cap__.png")
    try:
        img.save(tmp, format="PNG")
        tmp.replace(path)
    except Exception as exc:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        print(f"CAPTURE_ERR=save {exc}", path.name)
        return False
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    print(f"SAVED={path} size={img.size} md5={digest} hwnd={int(target)}")
    return True


# Alias used by older capture scripts.
capture_window = capture_miniai_window
