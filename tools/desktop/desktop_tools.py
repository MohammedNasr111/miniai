"""Desktop window listing, observation, and Stage 8b actions."""

from __future__ import annotations

import ctypes
import re
import threading
import time
from ctypes import wintypes
from typing import Any, Optional

import uiautomation as auto

from security.app_trust import (
    AppReadRefused,
    act_blocked_message,
    ensure_app_allowed,
    is_act_blocked,
    is_blocked,
    normalize_exe,
)
from security.gate import Tier, check_permission
from security import user_input_watch
from tools.desktop.task_grant import (
    clear_task_grant,
    current_grant_exe,
    has_grant_for,
    require_grant,
    set_task_grant,
)
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

ALWAYS_ASK_WORDS = frozenset(
    {
        "send",
        "delete",
        "remove",
        "submit",
        "pay",
        "buy",
        "purchase",
        "discard",
        "close",
        "exit",
        "uninstall",
        "erase",
        "reset",
        "publish",
        "post",
        "share",
        "format",
    }
)
ALWAYS_ASK_PHRASES = (
    "don't save",
    "dont save",
    "do not save",
    "sign out",
)

MAX_TITLE_CHARS = 120
MAX_ELEMENTS = 60
MAX_TEXT_CHARS = 3000
MAX_DEPTH = 12
MAX_NODES = 2000
WALK_JOIN_TIMEOUT_S = 6.0
PASSWORD_PLACEHOLDER = "[password field - not read]"
MAX_SET_TEXT_CHARS = 500
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4

# Session map: "w1" -> hwnd. Rebuilt on each desktop_list_windows call.
_window_handles: dict[str, int] = {}
# Last walk stats for tests / diagnostics.
_last_walk_stats: dict[str, Any] = {}
# Element snapshots from the most recent successful desktop_read_window.
_last_elements: dict[str, dict[str, Any]] = {}
_last_read_window_ref: Optional[str] = None
_last_read_hwnd: Optional[int] = None
_last_read_exe: Optional[str] = None


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


def _wrap_untrusted_body(body: str) -> str:
    return "\n".join([*PREAMBLE, BEGIN_MARKER, body, END_MARKER])


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
        body = "No visible windows."
    else:
        body = "\n".join(lines)
    return _wrap_untrusted_body(body)


def _normalize_window_ref(window: str) -> str:
    raw = (window or "").strip().lower()
    if raw.isdigit():
        raw = f"w{raw}"
    if not raw.startswith("w"):
        raw = f"w{raw}"
    return raw


def _resolve_window_ref(window: str) -> tuple[str, int, str, str]:
    raw = _normalize_window_ref(window)
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
    return raw, hwnd, exe, title


def _control_value(control: auto.Control) -> str:
    try:
        pattern = control.GetValuePattern()
    except Exception:
        pattern = None
    if pattern is None:
        try:
            pattern = control.GetPattern(auto.PatternId.ValuePattern)
        except Exception:
            pattern = None
    if pattern is not None:
        try:
            return str(pattern.Value or "")
        except Exception:
            return ""
    return ""


def _runtime_id(control: auto.Control) -> tuple:
    try:
        rid = control.GetRuntimeId()
        if rid is None:
            return ()
        return tuple(rid)
    except Exception:
        return ()


def _automation_id(control: auto.Control) -> str:
    try:
        return str(control.AutomationId or "")
    except Exception:
        return ""


def _snapshot_of(control: auto.Control) -> dict[str, Any]:
    try:
        ctype = control.ControlTypeName or "Control"
    except Exception:
        ctype = "Control"
    try:
        name = one_line(sanitize(control.Name or ""))[:80]
    except Exception:
        name = ""
    return {
        "control": control,
        "control_type": ctype,
        "name": name,
        "automation_id": _automation_id(control),
        "runtime_id": _runtime_id(control),
        "is_password": bool(getattr(control, "IsPassword", False)),
    }


def _walk_collect(
    root: auto.Control,
    words: list[str],
    collected: dict[str, Any],
    stop_event: threading.Event,
) -> None:
    """Walk the tree into ``collected`` until limits or stop_event."""
    elements: list[tuple[bool, dict[str, Any]]] = []
    text_parts: list[str] = []
    nodes = 0
    truncated_limits = False

    def visit(control: auto.Control, depth: int) -> None:
        nonlocal nodes, truncated_limits
        if stop_event.is_set() or truncated_limits:
            return
        if depth > MAX_DEPTH or nodes >= MAX_NODES:
            truncated_limits = True
            return
        nodes += 1
        collected["nodes"] = nodes
        try:
            snap = _snapshot_of(control)
            ctype = snap["control_type"]
            name = snap["name"]
            is_password = snap["is_password"]
        except Exception:
            return

        matched = False
        if words and name:
            lower = name.lower()
            matched = any(w in lower for w in words)

        if is_password:
            line = f'{ctype} "{PASSWORD_PLACEHOLDER}"'
        else:
            line = f'{ctype} "{name}"'
            value = ""
            try:
                if (
                    "Edit" in ctype
                    or "Document" in ctype
                    or "Text" in ctype
                ):
                    value = _control_value(control)
                    if not value and "Text" in ctype:
                        value = control.Name or ""
            except Exception:
                value = ""
            if value:
                text_parts.append(sanitize(value))
                collected["text_parts"] = list(text_parts)

        snap["line"] = line
        elements.append((matched, snap))
        collected["elements"] = list(elements)

        try:
            children = control.GetChildren()
        except Exception:
            children = []
        for child in children:
            if stop_event.is_set():
                return
            visit(child, depth + 1)

    try:
        visit(root, 0)
    except Exception as exc:
        collected["error"] = str(exc)
    collected["truncated_limits"] = truncated_limits
    collected["elements"] = list(elements)
    collected["text_parts"] = list(text_parts)
    collected["nodes"] = nodes
    collected["done"] = True


def _walk_window_threaded(
    root: auto.Control,
    words: list[str],
) -> tuple[list[tuple[bool, dict[str, Any]]], list[str], bool, bool, int]:
    """Run the UIA walk in a worker thread; join with a 6 s timeout."""
    collected: dict[str, Any] = {
        "elements": [],
        "text_parts": [],
        "nodes": 0,
        "truncated_limits": False,
        "done": False,
    }
    stop_event = threading.Event()

    def worker() -> None:
        _walk_collect(root, words, collected, stop_event)

    thread = threading.Thread(target=worker, name="miniai-uia-walk", daemon=True)
    thread.start()
    thread.join(WALK_JOIN_TIMEOUT_S)
    timed_out = thread.is_alive()
    if timed_out:
        stop_event.set()
        # Give the worker a moment to notice; do not wait forever.
        thread.join(0.5)
    elements = collected.get("elements") or []
    text_parts = collected.get("text_parts") or []
    truncated_limits = bool(collected.get("truncated_limits"))
    nodes = int(collected.get("nodes") or 0)
    return elements, text_parts, truncated_limits, timed_out, nodes


def _format_read_result(
    exe: str,
    title: str,
    elements: list[tuple[bool, dict[str, Any]]],
    text_parts: list[str],
    truncated_limits: bool,
    timed_out: bool,
    window_ref: str,
    hwnd: int,
) -> str:
    global _last_elements, _last_read_window_ref, _last_read_hwnd, _last_read_exe

    matched = [snap for flag, snap in elements if flag]
    rest = [snap for flag, snap in elements if not flag]
    ordered = matched + rest

    _last_elements = {}
    element_lines: list[str] = []
    for i, snap in enumerate(ordered[:MAX_ELEMENTS], start=1):
        key = f"e{i}"
        _last_elements[key] = snap
        element_lines.append(f"[{key}] {snap['line']}")

    _last_read_window_ref = window_ref
    _last_read_hwnd = hwnd
    _last_read_exe = exe

    text_blob = "\n".join(text_parts)
    if len(text_blob) > MAX_TEXT_CHARS:
        text_blob = text_blob[:MAX_TEXT_CHARS]
        truncated_limits = True

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
    if timed_out:
        body_lines.append("(truncated: the app did not respond in time)")
    elif truncated_limits:
        body_lines.append("(truncated: limits reached)")
    return _wrap_untrusted_body("\n".join(body_lines))


def _read_window_core(
    window_ref: str,
    hwnd: int,
    exe: str,
    title: str,
    looking_for: Optional[str] = None,
) -> str:
    words = looking_for_words(looking_for)
    started = time.perf_counter()
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception as exc:
        raise ValueError(f"Could not attach to window: {exc}") from exc

    elements, text_parts, truncated_limits, timed_out, nodes = _walk_window_threaded(
        root, words
    )
    elapsed = time.perf_counter() - started
    global _last_walk_stats
    _last_walk_stats = {
        "nodes": nodes,
        "wall_s": elapsed,
        "truncated": truncated_limits or timed_out,
        "timed_out": timed_out,
        "exe": exe,
        "title": title,
    }
    return _format_read_result(
        exe,
        title,
        elements,
        text_parts,
        truncated_limits,
        timed_out,
        window_ref,
        hwnd,
    )


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
    window_ref, hwnd, exe, title = _resolve_window_ref(window)
    try:
        ensure_app_allowed(exe, title)
    except AppReadRefused as exc:
        return str(exc)
    return _read_window_core(window_ref, hwnd, exe, title, looking_for)


def _normalize_element_ref(element: str) -> str:
    raw = (element or "").strip().lower()
    if raw.isdigit():
        raw = f"e{raw}"
    if not raw.startswith("e"):
        raw = f"e{raw}"
    return raw


def _name_needs_always_ask(name: str) -> bool:
    lower = (name or "").lower()
    for phrase in ALWAYS_ASK_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", lower):
            return True
    for word in ALWAYS_ASK_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return True
    return False


def _in_dialog(control: auto.Control) -> bool:
    cur: Any = control
    for _ in range(24):
        try:
            ctype = cur.ControlTypeName or ""
        except Exception:
            ctype = ""
        if "Dialog" in ctype:
            return True
        try:
            pattern = cur.GetPattern(auto.PatternId.WindowPattern)
            if pattern is not None and bool(getattr(pattern, "IsModal", False)):
                return True
        except Exception:
            pass
        try:
            if bool(getattr(cur, "IsModal", False)):
                return True
        except Exception:
            pass
        try:
            name = (cur.Name or "").lower()
            if "modal" in name and "Window" in ctype:
                return True
        except Exception:
            pass
        try:
            parent = cur.GetParentControl()
        except Exception:
            break
        if parent is None:
            break
        cur = parent
    return False


def _snapshots_match(stored: dict[str, Any], live: auto.Control) -> bool:
    try:
        ctype = live.ControlTypeName or "Control"
        name = one_line(sanitize(live.Name or ""))[:80]
        aid = _automation_id(live)
        rid = _runtime_id(live)
    except Exception:
        return False
    if ctype != stored.get("control_type"):
        return False
    if name != stored.get("name"):
        return False
    if aid != stored.get("automation_id"):
        return False
    stored_rid = stored.get("runtime_id") or ()
    if stored_rid and rid and stored_rid != rid:
        return False
    return True


def _resolve_element(element: str) -> dict[str, Any]:
    key = _normalize_element_ref(element)
    snap = _last_elements.get(key)
    if snap is None:
        raise ValueError(
            f"Unknown element {element!r}. Call desktop_read_window first "
            "and use a number from that result (e.g. e1)."
        )
    control = snap.get("control")
    if control is None:
        raise ValueError(
            "The window changed; read it again."
        )
    if not _snapshots_match(snap, control):
        raise ValueError("The window changed; read it again.")
    return snap


def _check_interrupt_or_end() -> Optional[str]:
    if not user_input_watch.is_interrupted():
        return None
    if user_input_watch.check_continue_after_interrupt():
        return None
    clear_task_grant()
    return (
        "Task ended: you used the mouse or keyboard and chose not to continue."
    )


def _validate_set_text(text: str) -> None:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string, got {type(text).__name__}")
    if len(text) > MAX_SET_TEXT_CHARS:
        raise ValueError(f"text must be at most {MAX_SET_TEXT_CHARS} characters")
    if _CONTROL_CHAR_RE.search(text):
        raise ValueError(
            "text must not contain control characters other than newline"
        )


def _fresh_read_after_action() -> str:
    if (
        _last_read_window_ref is None
        or _last_read_hwnd is None
        or _last_read_exe is None
    ):
        return "(no window read available)"
    title = _window_title(_last_read_hwnd)
    return _read_window_core(
        _last_read_window_ref,
        _last_read_hwnd,
        _last_read_exe,
        title,
        None,
    )


def desktop_begin_task(window: str, goal: str) -> str:
    """CONFIRM: grant desktop actions on one app for this user turn."""
    window_ref, hwnd, exe, title = _resolve_window_ref(window)
    if is_act_blocked(exe):
        return act_blocked_message(exe)
    safe_title = one_line(sanitize(title))[:MAX_TITLE_CHARS]
    safe_goal = one_line(sanitize(goal or ""))[:500]
    always_ask_list = (
        "send, delete, remove, submit, pay, buy, purchase, discard, "
        "don't save, close, exit, uninstall, erase, reset, sign out, "
        "publish, post, share, format; and any action inside a dialog"
    )
    description = (
        f"Allow MiniAI to CONTROL {exe} ({safe_title}) for this turn only?\n"
        f"Goal: {safe_goal}\n"
        "Allowed without further prompts: press ordinary buttons/links; "
        "set text in editable fields.\n"
        f"Always ask before (even with this grant): {always_ask_list}"
    )
    check_permission(
        action="desktop_begin_task",
        tier=Tier.CONFIRM,
        description=description,
    )
    # Reading must also be allowed for this app.
    try:
        ensure_app_allowed(exe, title)
    except AppReadRefused as exc:
        return str(exc)
    set_task_grant(exe, safe_goal, window_ref)
    read_back = _read_window_core(window_ref, hwnd, exe, title, None)
    return (
        f"Task grant active for {exe} this turn. Goal: {safe_goal}\n"
        f"{read_back}"
    )


def _try_press(control: auto.Control) -> str:
    # Invoke, then Toggle, then SelectionItem — never mouse movement.
    try:
        inv = control.GetInvokePattern()
    except Exception:
        inv = None
    if inv is None:
        try:
            inv = control.GetPattern(auto.PatternId.InvokePattern)
        except Exception:
            inv = None
    if inv is not None:
        try:
            inv.Invoke()
            return "invoked"
        except Exception:
            pass

    try:
        tog = control.GetTogglePattern()
    except Exception:
        tog = None
    if tog is None:
        try:
            tog = control.GetPattern(auto.PatternId.TogglePattern)
        except Exception:
            tog = None
    if tog is not None:
        try:
            tog.Toggle()
            return "toggled"
        except Exception:
            pass

    try:
        sel = control.GetSelectionItemPattern()
    except Exception:
        sel = None
    if sel is None:
        try:
            sel = control.GetPattern(auto.PatternId.SelectionItemPattern)
        except Exception:
            sel = None
    if sel is not None:
        try:
            sel.Select()
            return "selected"
        except Exception:
            pass

    # Last resort for some WinForms buttons: LegacyIAccessible DoDefaultAction.
    try:
        leg = control.GetLegacyIAccessiblePattern()
        if leg is not None:
            leg.DoDefaultAction()
            return "legacy-default"
    except Exception:
        pass

    raise ValueError("This element cannot be pressed (no Invoke/Toggle/SelectionItem).")


def desktop_press(element: str) -> str:
    """Press a previously read element (Invoke/Toggle/SelectionItem)."""
    check_permission(
        action="desktop_press",
        tier=Tier.AUTO_ALLOW,
        description=f"desktop_press {element}",
    )
    ended = _check_interrupt_or_end()
    if ended:
        return ended

    try:
        snap = _resolve_element(element)
    except ValueError as exc:
        return str(exc)
    exe = _last_read_exe or ""
    if is_act_blocked(exe):
        return act_blocked_message(exe)
    missing = require_grant(exe)
    if missing:
        return missing

    control = snap["control"]
    name = snap.get("name") or ""
    needs_ask = _name_needs_always_ask(name) or _in_dialog(control)
    if needs_ask:
        check_permission(
            action="desktop_press",
            tier=Tier.CONFIRM,
            description=(
                f"Press element [{_normalize_element_ref(element)}] "
                f"{snap.get('control_type')} \"{name}\" in {exe}."
            ),
        )

    ended = _check_interrupt_or_end()
    if ended:
        return ended

    try:
        method = _try_press(control)
    except ValueError as exc:
        return str(exc)
    read_back = _fresh_read_after_action()
    return f"Pressed ({method}) [{_normalize_element_ref(element)}] \"{name}\".\n{read_back}"


def desktop_set_text(element: str, text: str) -> str:
    """Set text on an edit control via ValuePattern (grant-covered)."""
    check_permission(
        action="desktop_set_text",
        tier=Tier.AUTO_ALLOW,
        description=f"desktop_set_text {element}",
    )
    ended = _check_interrupt_or_end()
    if ended:
        return ended

    try:
        _validate_set_text(text)
    except ValueError as exc:
        return str(exc)
    try:
        snap = _resolve_element(element)
    except ValueError as exc:
        return str(exc)
    exe = _last_read_exe or ""
    if is_act_blocked(exe):
        return act_blocked_message(exe)
    missing = require_grant(exe)
    if missing:
        return missing

    control = snap["control"]
    if snap.get("is_password") or bool(getattr(control, "IsPassword", False)):
        return "Refused: cannot set text on a password field."

    ctype = snap.get("control_type") or ""
    if "Edit" not in ctype and "Document" not in ctype:
        return (
            f"Refused: desktop_set_text requires an edit control, "
            f"got {ctype}."
        )

    try:
        pattern = control.GetValuePattern()
    except Exception:
        pattern = None
    if pattern is None:
        try:
            pattern = control.GetPattern(auto.PatternId.ValuePattern)
        except Exception:
            pattern = None
    if pattern is None:
        return "Refused: this control has no ValuePattern."
    try:
        if bool(getattr(pattern, "IsReadOnly", False)):
            return "Refused: this control is read-only."
    except Exception:
        pass

    if _in_dialog(control):
        shown = text.replace("\n", "\\n")
        check_permission(
            action="desktop_set_text",
            tier=Tier.CONFIRM,
            description=(
                f"Set text in dialog element [{_normalize_element_ref(element)}] "
                f"\"{snap.get('name')}\" ({len(text)} characters):\n{shown}"
            ),
        )

    ended = _check_interrupt_or_end()
    if ended:
        return ended

    pattern.SetValue(text)
    read_back = _fresh_read_after_action()
    return (
        f"Set text on [{_normalize_element_ref(element)}] "
        f"({len(text)} characters).\n{read_back}"
    )


def last_walk_stats() -> dict[str, Any]:
    """Copy of stats from the most recent desktop_read_window walk."""
    return dict(_last_walk_stats)


def clear_window_map() -> None:
    """Clear the session window-number map (tests / session reset)."""
    global _window_handles, _last_elements
    global _last_read_window_ref, _last_read_hwnd, _last_read_exe
    _window_handles = {}
    _last_elements = {}
    _last_read_window_ref = None
    _last_read_hwnd = None
    _last_read_exe = None
