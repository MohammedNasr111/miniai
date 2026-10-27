"""Redact API keys from agent log payloads before writing to disk."""

from __future__ import annotations

import re
from typing import Any

# Google API keys look like AIza… (39 chars typical). Also redact stored key.
_AIZA_RE = re.compile(r"AIza[0-9A-Za-z_-]{10,}")


def _stored_key() -> str:
    try:
        from security.gemini_key import load_key

        return (load_key() or "").strip()
    except Exception:
        return ""


def redact_text(text: str, *, extra_secrets: list[str] | None = None) -> str:
    if not text:
        return text
    out = text
    secrets = list(extra_secrets or [])
    sk = _stored_key()
    if sk:
        secrets.append(sk)
    for s in secrets:
        if s and s in out:
            out = out.replace(s, "[REDACTED_API_KEY]")
    out = _AIZA_RE.sub("[REDACTED_API_KEY]", out)
    return out


def redact_obj(obj: Any, *, extra_secrets: list[str] | None = None) -> Any:
    if isinstance(obj, str):
        return redact_text(obj, extra_secrets=extra_secrets)
    if isinstance(obj, dict):
        return {
            k: redact_obj(v, extra_secrets=extra_secrets) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v, extra_secrets=extra_secrets) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(v, extra_secrets=extra_secrets) for v in obj)
    return obj
