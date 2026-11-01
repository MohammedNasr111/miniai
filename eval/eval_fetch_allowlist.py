"""Eval-only fetch allow-list for one fixture host:port while eval.lock is live.

Does not weaken the product loopback/private block outside evals.
"""

from __future__ import annotations

import threading
from typing import Optional
from urllib.parse import urlparse

_lock = threading.Lock()
# Exact (hostname.lower(), port) pairs permitted only while eval.lock is live.
_allowed: set[tuple[str, int]] = set()


def clear_eval_fetch_allowlist() -> None:
    with _lock:
        _allowed.clear()


def allow_eval_fetch_host_port(host: str, port: int) -> None:
    """Register one fixture host:port for fetch during a live eval lock."""
    h = (host or "").strip().lower().rstrip(".")
    p = int(port)
    if not h or p <= 0 or p > 65535:
        raise ValueError(f"invalid eval fetch allow host/port: {host!r}:{port!r}")
    with _lock:
        _allowed.add((h, p))


def revoke_eval_fetch_host_port(host: str, port: int) -> None:
    h = (host or "").strip().lower().rstrip(".")
    p = int(port)
    with _lock:
        _allowed.discard((h, p))


def list_eval_fetch_allowlist() -> list[tuple[str, int]]:
    with _lock:
        return sorted(_allowed)


def is_eval_fetch_allowed(url: str) -> bool:
    """True only if eval.lock is live and url host:port is explicitly allowed."""
    try:
        from eval.eval_lock import eval_lock_is_live

        live, _why = eval_lock_is_live()
    except Exception:
        return False
    if not live:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is None:
        scheme = (parsed.scheme or "").lower()
        port = 443 if scheme == "https" else 80
    with _lock:
        return (host, int(port)) in _allowed
