"""Read-only desktop window listing and UI Automation observation."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Optional

import uiautomation as auto

from security.app_trust import (
    AppReadRefused,
    ensure_app_allowed,
    is_blocked,
    normalize_exe,
)
from security.gate import Tier, check_permission
from tools.web.untrusted import (
    BEGIN_MARKER,
    END_MARKER,
    PREAMBLE,
    one_line,
    sanitize,
)

# Same stop words as tools.browser.session.looking_for_words.
_LOOKING_FOR_STOP = frozenset(
    {
        "first",
        "last",
        "sentence",
        "sentences",
        "paragraph",
        "page",
        "article",
        "text",
        "section",
        "heading",
        "the",
        "a",
        "an",
        "of",
        "and",
        "to",
        "in",
        "on",
        "for",
    }
)

MAX_TITLE_CHARS = 120
MAX_ELEMENTS = 60
MAX_TEXT_CHARS = 3000
MAX_DEPTH = 12
MAX_NODES = 2000
WALK_TIMEOUT_S = 5.0
PASSWORD_PLACEHOLDER = "[password field - not read]"

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4

# Session map: "w1" -> hwnd. Rebuilt on each desktop_list_windows call.
_window_handles: dict[str, int] = {}
# Last walk stats for tests / diagnostics.
_last_walk_stats: dict[str, Any] = {}


def looking_for_words(looking_for: Optional[str]) -> list[str]:
    raw = (looking_for or "").lower()
    return [w for w in raw.split() if w and w not in _LOOKING_FOR_STOP]


def exe_for_hwnd(hwnd: int) -> str:
    """Return the lowercase executable basename for a window handle."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return "unknown.exe"
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value
    )
    if not handle:
        return "unknown.exe"
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return normalize_exe(buf.value)
        return "unknown.exe"
    finally:
        kernel32.CloseHandle(handle)


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def _enumerate_top_level() -> list[tuple[int, str, str]]:
    """Visible top-level windows as (hwnd, exe, title), blocked omitted."""
    found: list[tuple[int, str, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        title = _window_title(hwnd)
        if not title.strip():
            return True
        exe = exe_for_hwnd(hwnd)
        if is_blocked(exe, title):
            return True
        found.append((int(hwnd), exe, title))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def desktop_list_windows() -> str:
    """List visible top-level windows as [wN] exe - title. AUTO_ALLOW."""
    check_permission(
        action="desktop_list_windows",
        tier=Tier.AUTO_ALLOW,
        description="List visible desktop windows (read-only).",
    )
    global _window_handles
    rows = _enumerate_top_level()
    _window_handles = {}
    lines: list[str] = []
    for index, (hwnd, exe, title) in enumerate(rows, start=1):
        key = f"w{index}"
        _window_handles[key] = hwnd
        safe_title = one_line(sanitize(title))[:MAX_TITLE_CHARS]
        lines.append(f"[{key}] {exe} - {safe_title}")
    if not lines:
        return "No visible windows."
    return "\n".join(lines)


def _resolve_window_ref(window: str) -> tuple[int, str, str]:
    raw = (window or "").strip().lower()
    if raw.isdigit():
        raw = f"w{raw}"
    if not raw.startswith("w"):
        raw = f"w{raw}"
    hwnd = _window_handles.get(raw)
    if hwnd is None:
        raise ValueError(
            f"Unknown window ref {window!r}. Call desktop_list_windows first "
            "and use a number from that list (e.g. w1)."
        )
    if not user32.IsWindow(hwnd):
        raise ValueError(
            f"Window {raw} is no longer open. Call desktop_list_windows again."
        )
    title = _window_title(hwnd)
    exe = exe_for_hwnd(hwnd)
    return hwnd, exe, title


def _control_value(control: auto.Control) -> str:
    try:
        pattern = control.GetValuePattern()
    except Exception:
        pattern = None
    if pattern is not None:
        try:
            return str(pattern.Value or "")
        except Exception:
            return ""
    return ""


def _walk_window(
    root: auto.Control,
    words: list[str],
) -> tuple[list[tuple[bool, str]], list[str], bool, int]:
    """Return (ranked element lines with match flag, text pieces, truncated, nodes)."""
    elements: list[tuple[bool, str]] = []
    text_parts: list[str] = []
    nodes = 0
    truncated = False
    started = time.perf_counter()

    def visit(control: auto.Control, depth: int) -> None:
        nonlocal nodes, truncated
        if truncated:
            return
        if depth > MAX_DEPTH or nodes >= MAX_NODES:
            truncated = True
            return
        if time.perf_counter() - started >= WALK_TIMEOUT_S:
            truncated = True
            return
        nodes += 1
        try:
            ctype = control.ControlTypeName or "Control"
            name = one_line(sanitize(control.Name or ""))[:80]
            is_password = bool(getattr(control, "IsPassword", False))
        except Exception:
            return

        matched = False
        if words and name:
            lower = name.lower()
            matched = any(w in lower for w in words)

        if is_password:
            elements.append((matched, f"{ctype} \"{PASSWORD_PLACEHOLDER}\""))
        else:
            elements.append((matched, f'{ctype} "{name}"'))
            value = ""
            try:
                if ctype in (
                    "EditControl",
                    "DocumentControl",
                    "TextControl",
                    "Edit",
                    "Document",
                    "Text",
                ) or "Edit" in ctype or "Document" in ctype or "Text" in ctype:
                    value = _control_value(control)
                    if not value and ctype in ("TextControl", "Text"):
                        value = control.Name or ""
            except Exception:
                value = ""
            if value:
                text_parts.append(sanitize(value))

        try:
            children = control.GetChildren()
        except Exception:
            children = []
        for child in children:
            visit(child, depth + 1)

    visit(root, 0)
    return elements, text_parts, truncated, nodes


def desktop_read_window(
    window: str,
    looking_for: Optional[str] = None,
) -> str:
    """Read a listed window's UI tree (read-only). AUTO_ALLOW + app trust."""
    check_permission(
        action="desktop_read_window",
        tier=Tier.AUTO_ALLOW,
        description=f"Read desktop window {window!r} (read-only).",
    )
    hwnd, exe, title = _resolve_window_ref(window)
    try:
        ensure_app_allowed(exe, title)
    except AppReadRefused as exc:
        return str(exc)

    words = looking_for_words(looking_for)
    started = time.perf_counter()
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception as exc:
        raise ValueError(f"Could not attach to window: {exc}") from exc

    elements, text_parts, truncated, nodes = _walk_window(root, words)
    elapsed = time.perf_counter() - started
    global _last_walk_stats
    _last_walk_stats = {
        "nodes": nodes,
        "wall_s": elapsed,
        "truncated": truncated,
        "exe": exe,
        "title": title,
    }

    # Matched elements first, preserve relative order within each group.
    matched = [line for flag, line in elements if flag]
    rest = [line for flag, line in elements if not flag]
    ordered = matched + rest
    element_lines = [
        f"[e{i}] {line}" for i, line in enumerate(ordered[:MAX_ELEMENTS], start=1)
    ]

    text_blob = "\n".join(text_parts)
    if len(text_blob) > MAX_TEXT_CHARS:
        text_blob = text_blob[:MAX_TEXT_CHARS]
        truncated = True

    safe_title = one_line(sanitize(title))[:MAX_TITLE_CHARS]
    body_lines = [
        f"Executable: {sanitize(exe)}",
        f"Window title: {safe_title}",
        "Elements:",
    ]
    if element_lines:
        body_lines.extend(element_lines)
    else:
        body_lines.append("(no elements)")
    body_lines.append("Text:")
    body_lines.append(text_blob if text_blob.strip() else "(no text)")
    if truncated:
        body_lines.append("(truncated: limits reached)")

    lines = [
        *PREAMBLE,
        BEGIN_MARKER,
        "\n".join(body_lines),
        END_MARKER,
    ]
    return "\n".join(lines)


def last_walk_stats() -> dict[str, Any]:
    """Copy of stats from the most recent desktop_read_window walk."""
    return dict(_last_walk_stats)


def clear_window_map() -> None:
    """Clear the session window-number map (tests / session reset)."""
    global _window_handles
    _window_handles = {}
