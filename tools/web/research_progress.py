"""Optional UI progress hooks while web_research runs (no-op in CLI)."""

from __future__ import annotations

from typing import Any, Callable, Optional

_ProgressCb = Callable[[str, dict[str, Any]], None]
_cb: Optional[_ProgressCb] = None


def set_research_progress(cb: Optional[_ProgressCb]) -> None:
    global _cb
    _cb = cb


def emit_research_progress(kind: str, **payload: Any) -> None:
    cb = _cb
    if cb is None:
        return
    try:
        cb(kind, dict(payload))
    except Exception:
        pass
