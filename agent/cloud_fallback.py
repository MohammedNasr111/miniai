"""Visible cloud→local fallback reasons (never silent)."""

from __future__ import annotations

import re
from typing import Optional

# Stable reason category codes (Round 8b/8c).
REASON_QUOTA = "quota"
REASON_KEY_REJECTED = "key rejected"
REASON_NETWORK = "network"
REASON_TIMEOUT = "timeout"
REASON_SETTING_OFF = "setting off"
REASON_ERROR = "error"
REASON_SERVER_BUSY = "server busy"

FALLBACK_UNUSED_TMPL = "Gemini wasn't used: {reason}. Answered on this PC."
FALLBACK_PARTIAL_TMPL = (
    "Gemini stopped partway ({reason}); this PC finished the answer."
)


def _redact_secrets(text: str) -> str:
    """Strip API-key-shaped tokens from Google error messages."""
    s = text or ""
    s = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "[REDACTED_API_KEY]", s)
    s = re.sub(
        r"(?i)(api[_\s-]?key|bearer|authorization)\s*[:=]\s*\S+",
        r"\1=[REDACTED_API_KEY]",
        s,
    )
    return s


def _google_error_bits(exc: BaseException) -> tuple[Optional[int], str, str]:
    """Return (http_status, google_status_code, short_message) when present."""
    status = getattr(exc, "http_status", None)
    gcode = str(getattr(exc, "google_status", None) or "").strip()
    msg = str(getattr(exc, "google_message", None) or "").strip()
    if status is None:
        m = re.search(r"\b([45]\d\d)\b", str(exc))
        if m:
            try:
                status = int(m.group(1))
            except ValueError:
                status = None
    if not gcode:
        m = re.search(
            r"\b(RESOURCE_EXHAUSTED|UNAVAILABLE|PERMISSION_DENIED|UNAUTHENTICATED|"
            r"INVALID_ARGUMENT|NOT_FOUND|INTERNAL|DEADLINE_EXCEEDED)\b",
            str(exc),
            re.I,
        )
        if m:
            gcode = m.group(1).upper()
    if not msg:
        msg = str(exc).strip()
    return (
        int(status) if status is not None else None,
        gcode,
        _redact_secrets(msg)[:160],
    )


def format_reason_detail(
    category: str,
    *,
    http_status: Optional[int] = None,
    google_status: str = "",
    google_message: str = "",
) -> str:
    """User-facing reason: category plus safe HTTP/Google detail."""
    cat = (category or REASON_ERROR).strip() or REASON_ERROR
    parts: list[str] = []
    if http_status is not None:
        parts.append(str(int(http_status)))
    gs = (google_status or "").strip()
    if gs:
        parts.append(gs)
    gm = _redact_secrets((google_message or "").strip())
    # Avoid duplicating a long message when status already tells the story.
    if gm and gs and gs.lower() not in gm.lower() and len(gm) < 80:
        # Prefer compact: "quota (429 RESOURCE_EXHAUSTED)" without essay.
        pass
    if parts:
        return f"{cat} ({' '.join(parts)})"
    return cat


def classify_cloud_error(exc: BaseException) -> str:
    """Map an exception to a short fallback reason with safe HTTP/Google detail."""
    from llm.gemini.provider import (
        GeminiAuthError,
        GeminiConfigError,
        GeminiHttpError,
        GeminiQuotaError,
    )

    http_status, gcode, gmsg = _google_error_bits(exc)

    if isinstance(exc, GeminiQuotaError):
        return format_reason_detail(
            REASON_QUOTA,
            http_status=http_status or 429,
            google_status=gcode or "RESOURCE_EXHAUSTED",
            google_message=gmsg,
        )
    if isinstance(exc, GeminiAuthError):
        return format_reason_detail(
            REASON_KEY_REJECTED,
            http_status=http_status or 401,
            google_status=gcode,
            google_message=gmsg,
        )
    if isinstance(exc, GeminiHttpError):
        code = http_status or getattr(exc, "http_status", None)
        if code == 429:
            return format_reason_detail(
                REASON_QUOTA,
                http_status=429,
                google_status=gcode or "RESOURCE_EXHAUSTED",
                google_message=gmsg,
            )
        if code is not None and int(code) >= 500:
            return format_reason_detail(
                REASON_SERVER_BUSY,
                http_status=int(code),
                google_status=gcode or "UNAVAILABLE",
                google_message=gmsg,
            )
        return format_reason_detail(
            REASON_ERROR,
            http_status=int(code) if code is not None else None,
            google_status=gcode,
            google_message=gmsg,
        )
    if isinstance(exc, GeminiConfigError):
        msg = str(exc).lower()
        if "key" in msg or "no gemini" in msg:
            return REASON_KEY_REJECTED
        return format_reason_detail(REASON_ERROR, google_message=str(exc)[:80])

    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text or "deadline" in text:
        return format_reason_detail(
            REASON_TIMEOUT,
            http_status=http_status,
            google_status=gcode or "DEADLINE_EXCEEDED",
            google_message=gmsg,
        )
    if any(
        x in name or x in text
        for x in (
            "connection",
            "network",
            "dns",
            "ssl",
            "proxy",
            "unreachable",
            "name resolution",
        )
    ):
        return format_reason_detail(REASON_NETWORK, google_message=gmsg)
    if "429" in text or "quota" in text or "resource exhausted" in text:
        return format_reason_detail(
            REASON_QUOTA,
            http_status=http_status or 429,
            google_status=gcode or "RESOURCE_EXHAUSTED",
            google_message=gmsg,
        )
    if "503" in text or "unavailable" in text or "high demand" in text:
        return format_reason_detail(
            REASON_SERVER_BUSY,
            http_status=http_status or 503,
            google_status=gcode or "UNAVAILABLE",
            google_message=gmsg,
        )
    if "401" in text or "403" in text or "rejected" in text or "api key" in text:
        return format_reason_detail(
            REASON_KEY_REJECTED,
            http_status=http_status,
            google_status=gcode,
            google_message=gmsg,
        )
    if http_status is not None and int(http_status) >= 500:
        return format_reason_detail(
            REASON_SERVER_BUSY,
            http_status=int(http_status),
            google_status=gcode,
            google_message=gmsg,
        )
    return format_reason_detail(
        REASON_ERROR,
        http_status=http_status,
        google_status=gcode,
        google_message=gmsg,
    )


def fallback_header(reason: str, *, used_gemini: bool = False) -> str:
    """Visible header. 'wasn't used' only when no Gemini response was consumed."""
    detail = (reason or REASON_ERROR).strip() or REASON_ERROR
    if used_gemini:
        return FALLBACK_PARTIAL_TMPL.format(reason=detail)
    return FALLBACK_UNUSED_TMPL.format(reason=detail)


def coerce_cloud_flag(value: object) -> bool:
    """JS/pywebview may pass bool, int, or string."""
    if value is True or value is False:
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "cloud"}
    return False


def quota_block_message(now: float | None = None) -> Optional[str]:
    """If a quota hit was recorded in the past hour, refuse to start a cloud turn."""
    import time
    from datetime import datetime

    from app.prefs import get_gemini_quota_blocked_until

    hit_at = get_gemini_quota_blocked_until()
    if hit_at is None:
        return None
    t = float(now if now is not None else time.time())
    if t - float(hit_at) > 3600.0:
        return None
    try:
        when = datetime.fromtimestamp(float(hit_at)).astimezone().strftime("%H:%M")
    except (OSError, OverflowError, ValueError):
        when = "earlier"
    return (
        f"Gemini's free limit was reached at {when}. "
        "Try later or send normally."
    )


def note_quota_hit(when: float | None = None) -> None:
    import time

    from app.prefs import set_gemini_quota_hit_at

    set_gemini_quota_hit_at(float(when if when is not None else time.time()))
