"""OS path helpers that do not follow a redirected LOCALAPPDATA env var."""

from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

# https://learn.microsoft.com/windows/win32/shell/knownfolderid
_FOLDERID_LOCAL_APPDATA = uuid.UUID("{F1B32785-286F-410B-A947-75274DF0EEB8}")
_CSIDL_LOCAL_APPDATA = 0x001C


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_from_uuid(u: uuid.UUID) -> _GUID:
    return _GUID(
        u.fields[0],
        u.fields[1],
        u.fields[2],
        (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]),
    )


def real_local_appdata() -> Path:
    """User's real Local AppData (ignores the LOCALAPPDATA environment variable).

    Prefers SHGetKnownFolderPath(FOLDERID_LocalAppData). Some Windows installs
    return FILE_NOT_FOUND for that ID even when Local AppData exists; fall back
    to SHGetFolderPathW(CSIDL_LOCAL_APPDATA), which also ignores the env var.
    """
    if os.name != "nt":
        return Path.home() / ".local" / "share"

    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
    try:
        ole32.CoInitialize(None)
    except OSError:
        pass

    SHGetKnownFolderPath = shell32.SHGetKnownFolderPath
    SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    SHGetKnownFolderPath.restype = ctypes.c_long

    folder_id = _guid_from_uuid(_FOLDERID_LOCAL_APPDATA)
    path_ptr = ctypes.c_wchar_p()
    hr = SHGetKnownFolderPath(
        ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr)
    )
    if hr == 0 and path_ptr.value:
        try:
            return Path(path_ptr.value)
        finally:
            ole32.CoTaskMemFree(path_ptr)

    # Fallback: classic CSIDL path (still known-folder based; ignores env).
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    hr2 = shell32.SHGetFolderPathW(None, _CSIDL_LOCAL_APPDATA, None, 0, buf)
    if hr2 == 0 and buf.value:
        return Path(buf.value)
    raise OSError(
        f"Could not resolve Local AppData "
        f"(SHGetKnownFolderPath=0x{hr & 0xFFFFFFFF:08X}, "
        f"SHGetFolderPathW=0x{hr2 & 0xFFFFFFFF:08X})"
    )


def ensure_playwright_browsers_path() -> Path:
    """Point Playwright at the real ms-playwright install when unset/sandbox."""
    existing = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if existing and "cursor-sandbox-cache" not in existing:
        return Path(existing)
    path = real_local_appdata() / "ms-playwright"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
    return path
