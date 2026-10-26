"""OS path helpers that do not follow a redirected LOCALAPPDATA env var."""

from __future__ import annotations

import ctypes
import os
import re
import uuid
import winreg
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

# https://learn.microsoft.com/windows/win32/shell/knownfolderid
_FOLDERID_LOCAL_APPDATA = uuid.UUID("{F1B32785-286F-410B-A947-75274DF0EEB8}")
_CSIDL_LOCAL_APPDATA = 0x001C

# User-facing folders (OneDrive-redirected on many installs).
_USER_FOLDER_IDS: dict[str, uuid.UUID] = {
    "Desktop": uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"),
    "Documents": uuid.UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"),
    "Downloads": uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}"),
    "Pictures": uuid.UUID("{33E28130-4E1E-4676-835A-98395C3BC3BB}"),
    "Music": uuid.UUID("{4BD8D571-6D19-48D3-BE97-422220080E43}"),
    "Videos": uuid.UUID("{18989B1D-99B3-485B-A866-BF58795BF3F5}"),
}

# HKCU\...\Explorer\User Shell Folders value names
_USER_SHELL_REG: dict[str, str] = {
    "Desktop": "Desktop",
    "Documents": "Personal",
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "Pictures": "My Pictures",
    "Music": "My Music",
    "Videos": "My Video",
}

USER_FOLDER_NAMES: tuple[str, ...] = tuple(_USER_FOLDER_IDS.keys())

_user_folders_cache: Optional[dict[str, Path]] = None


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


def _sh_get_known_folder(folder_id: uuid.UUID) -> Optional[Path]:
    if os.name != "nt":
        return None
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
    guid = _guid_from_uuid(folder_id)
    path_ptr = ctypes.c_wchar_p()
    hr = SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_ptr))
    if hr == 0 and path_ptr.value:
        try:
            return Path(path_ptr.value)
        finally:
            ole32.CoTaskMemFree(path_ptr)
    return None


def _registry_user_shell_folder(reg_name: str) -> Optional[Path]:
    if os.name != "nt":
        return None
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            raw, _ = winreg.QueryValueEx(key, reg_name)
    except OSError:
        return None
    expanded = os.path.expandvars(str(raw or "").strip())
    if not expanded:
        return None
    return Path(expanded)


def _default_home_folder(name: str) -> Path:
    return Path.home() / name


def resolve_user_folders(
    *,
    known_folder_getter: Optional[Callable[[str], Optional[Path]]] = None,
    registry_getter: Optional[Callable[[str], Optional[Path]]] = None,
    use_cache: bool = True,
) -> dict[str, Path]:
    """Resolve Desktop, Documents, Downloads, Pictures, Music, Videos.

    Order per folder: SHGetKnownFolderPath(FOLDERID_*), then registry
    User Shell Folders, then Path.home()/Name.
    """
    global _user_folders_cache
    if use_cache and known_folder_getter is None and registry_getter is None:
        if _user_folders_cache is not None:
            return dict(_user_folders_cache)

    out: dict[str, Path] = {}
    for name in USER_FOLDER_NAMES:
        path: Optional[Path] = None
        if known_folder_getter is not None:
            path = known_folder_getter(name)
        else:
            path = _sh_get_known_folder(_USER_FOLDER_IDS[name])
        if path is None:
            reg = _USER_SHELL_REG[name]
            if registry_getter is not None:
                path = registry_getter(reg)
            else:
                path = _registry_user_shell_folder(reg)
        if path is None:
            path = _default_home_folder(name)
        out[name] = Path(path)

    if use_cache and known_folder_getter is None and registry_getter is None:
        _user_folders_cache = dict(out)
    return out


def clear_user_folders_cache() -> None:
    global _user_folders_cache
    _user_folders_cache = None


def user_folders_prompt_line(
    folders: Optional[dict[str, Path]] = None,
) -> str:
    """System-prompt sentence listing real user folder paths."""
    folders = folders or resolve_user_folders()
    parts = [f"{name} = {folders[name]}" for name in USER_FOLDER_NAMES]
    return "The user's folders: " + ", ".join(parts) + "."


_ENV_VAR_RE = re.compile(r"%([^%]+)%")


def expand_user_path(
    path: str,
    *,
    folders: Optional[dict[str, Path]] = None,
) -> Path:
    """Expand ~/Desktop, Desktop\\…, %USERPROFILE%\\Desktop, etc. to real folders."""
    raw = (path or "").strip()
    if not raw:
        return Path(raw)

    folders = folders or resolve_user_folders()
    name_by_lower = {n.lower(): n for n in folders}

    # Expand %VAR% but remap %USERPROFILE%\<Folder>\… to known folders.
    def _env_sub(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), m.group(0))

    s = _ENV_VAR_RE.sub(_env_sub, raw)
    if s.startswith("~"):
        # ~/Desktop/... → known Desktop, not Path.home()/Desktop
        rest = s[1:].lstrip("/\\")
        if rest:
            first, _, tail = rest.replace("/", "\\").partition("\\")
            key = name_by_lower.get(first.lower())
            if key is not None:
                return folders[key] / tail if tail else folders[key]
        s = str(Path.home() / rest) if rest else str(Path.home())

    norm = s.replace("/", "\\")
    p = Path(norm)

    # Relative: Desktop\file.txt
    if not p.is_absolute():
        parts = p.parts
        if parts:
            key = name_by_lower.get(parts[0].lower())
            if key is not None:
                return folders[key].joinpath(*parts[1:])
        return p

    # Absolute under Path.home()/Name (wrong when OneDrive-redirected)
    home = Path.home()
    try:
        resolved_home = home.resolve()
    except OSError:
        resolved_home = home
    for name, real in folders.items():
        wrong = home / name
        try:
            wrong_res = wrong.resolve()
        except OSError:
            wrong_res = wrong
        # Exact match or child of the non-redirected home\Name
        for candidate in (wrong, wrong_res, resolved_home / name):
            try:
                rel = p.resolve().relative_to(candidate.resolve())
            except (ValueError, OSError):
                try:
                    # Compare without requiring paths to exist
                    pref = str(candidate).rstrip("\\/")
                    ps = str(p)
                    if ps.lower() == pref.lower():
                        return real
                    if ps.lower().startswith(pref.lower() + "\\"):
                        return real / ps[len(pref) + 1 :]
                except Exception:
                    continue
                continue
            else:
                return real.joinpath(*rel.parts)

    # Also: already-correct known folder paths stay as-is
    return p


def ensure_playwright_browsers_path() -> Path:
    """Point Playwright at the real ms-playwright install when unset/sandbox."""
    existing = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if existing and "cursor-sandbox-cache" not in existing:
        return Path(existing)
    path = real_local_appdata() / "ms-playwright"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
    return path
