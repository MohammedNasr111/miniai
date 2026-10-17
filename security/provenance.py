"""Per-session set of URLs the user or tools have already surfaced.

Used by the permission gate: in a tainted session, fetch_url / browser_open
of a URL not in this set requires typing the action name (the model built
it). Cleared with reset_session().
"""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

# http(s) URLs in free text; trim common trailing punctuation after the match.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

_known: set[str] = set()


def clear_known_urls() -> None:
    """Empty the known set (called from reset_session)."""
    _known.clear()


def normalize_url(url: str) -> Optional[str]:
    """Lowercase scheme and host; empty path -> '/'; keep path/query/fragment.

    Uses urlsplit so path segments that include ';' stay in the path
    (urlparse would peel them into a separate params field).
    """
    raw = (url or "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    if parts.port is not None:
        netloc = f"{host}:{parts.port}"
    else:
        netloc = host
    path = parts.path if parts.path else "/"
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def remember_url(url: str) -> None:
    """Add one URL to the known set if it normalizes as http(s)."""
    normalized = normalize_url(url)
    if normalized is not None:
        _known.add(normalized)


def remember_urls(urls: Iterable[str]) -> None:
    for url in urls:
        remember_url(url)


def is_known_url(url: str) -> bool:
    normalized = normalize_url(url)
    return normalized is not None and normalized in _known


def remember_urls_from_text(text: str) -> None:
    """Register every http(s) URL appearing in free text (e.g. a user message)."""
    for match in _URL_RE.finditer(text or ""):
        candidate = match.group(0).rstrip(".,;:!?")
        remember_url(candidate)


def known_urls() -> frozenset[str]:
    """Snapshot for tests."""
    return frozenset(_known)
