"""Per-turn desktop task grant for Stage 8b actions."""

from __future__ import annotations

from typing import Optional

from security import user_input_watch

# Grant is for one executable for the current user turn only.
_grant_exe: Optional[str] = None
_grant_goal: Optional[str] = None
_grant_window_ref: Optional[str] = None


def clear_task_grant() -> None:
    """End the current grant and uninstall the input watch."""
    global _grant_exe, _grant_goal, _grant_window_ref
    _grant_exe = None
    _grant_goal = None
    _grant_window_ref = None
    user_input_watch.stop_watch()


def set_task_grant(exe: str, goal: str, window_ref: str) -> None:
    global _grant_exe, _grant_goal, _grant_window_ref
    clear_task_grant()
    _grant_exe = exe.lower()
    _grant_goal = goal
    _grant_window_ref = window_ref
    user_input_watch.start_watch()


def current_grant_exe() -> Optional[str]:
    return _grant_exe


def has_grant_for(exe: str) -> bool:
    return _grant_exe is not None and _grant_exe == exe.lower()


def require_grant(exe: str) -> Optional[str]:
    """Return an error message if there is no grant for this exe, else None."""
    if _grant_exe is None:
        return "Call desktop_begin_task first."
    if _grant_exe != exe.lower():
        return (
            f"Call desktop_begin_task first. "
            f"(Current grant is for {_grant_exe}, not {exe.lower()}.)"
        )
    return None
