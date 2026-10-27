"""Visible cloud→local fallback reasons (never silent)."""

from __future__ import annotations

from typing import Optional

# Stable reason codes → user-facing phrases (Round 8b).
REASON_QUOTA = "quota"
REASON_KEY_REJECTED = "key rejected"
REASON_NETWORK = "network"
REASON_TIMEOUT = "timeout"
REASON_SETTING_OFF = "setting off"
REASON_ERROR = "error"

FALLBACK_HEADER_TMPL = "Gemini wasn't used: {reason}. Answered on this PC."


def classify_cloud_error(exc: BaseException) -> str:
    """Map an exception to a short fallback reason phrase."""
    from llm.gemini.provider import GeminiAuthError, GeminiConfigError, GeminiQuotaError

    if isinstance(exc, GeminiQuotaError):
        return REASON_QUOTA
    if isinstance(exc, GeminiAuthError):
        return REASON_KEY_REJECTED
    if isinstance(exc, GeminiConfigError):
        msg = str(exc).lower()
        if "key" in msg or "no gemini" in msg:
            return REASON_KEY_REJECTED
        return REASON_ERROR
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return REASON_TIMEOUT
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
        return REASON_NETWORK
    if "429" in text or "quota" in text or "resource exhausted" in text:
        return REASON_QUOTA
    if "401" in text or "403" in text or "rejected" in text or "api key" in text:
        return REASON_KEY_REJECTED
    return REASON_ERROR


def fallback_header(reason: str) -> str:
    return FALLBACK_HEADER_TMPL.format(reason=(reason or REASON_ERROR).strip())


def coerce_cloud_flag(value: object) -> bool:
    """JS/pywebview may pass bool, int, or string."""
    if value is True or value is False:
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "cloud"}
    return False
