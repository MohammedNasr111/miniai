"""Deterministic remember-intent: code calls save_memory before the model."""

from __future__ import annotations

import re
from typing import Optional

from agent.action_claim_check import user_has_remember_intent

_LEADING = re.compile(
    r"(?i)^\s*(?:please\s+)?"
    r"(?:"
    r"remember(?:\s+that)?"
    r"|don't\s+forget(?:\s+that)?"
    r"|do\s+not\s+forget(?:\s+that)?"
    r"|note\s+that"
    r"|keep\s+in\s+mind(?:\s+that)?"
    r"|save\s+this"
    r"|save\s+that"
    r")\s*[,:]?\s*"
)


def extract_remember_fact(user_text: str) -> Optional[str]:
    """Strip the remember-intent lead-in; return the rest verbatim (or None)."""
    text = (user_text or "").strip()
    if not text or not user_has_remember_intent(text):
        return None
    rest = _LEADING.sub("", text, count=1).strip()
    if not rest or rest == text:
        # Lead-in not at start (e.g. mid-sentence) — use full text as fact.
        rest = text
    return rest or None


def guess_memory_category(fact: str) -> str:
    low = (fact or "").lower()
    if any(
        k in low
        for k in (
            "favourite",
            "favorite",
            "prefer",
            "like",
            "colour",
            "color",
        )
    ):
        return "preference"
    return "fact"


def code_save_remember_intent(user_text: str) -> Optional[dict]:
    """If remember-intent, call save_memory (respecting its CONFIRM tier).

    Returns {"fact", "category", "result"} on success, None if skipped/denied.
    """
    fact = extract_remember_fact(user_text)
    if not fact:
        return None
    category = guess_memory_category(fact)
    from security.gate import PermissionDenied
    from tools.memory.memory_tools import save_memory

    try:
        result = save_memory(content=fact, category=category)
    except (PermissionDenied, EOFError) as exc:
        return {"fact": fact, "category": category, "error": str(exc), "ok": False}
    except Exception as exc:
        # Unexpected errors — leave it to the model path.
        return {"fact": fact, "category": category, "error": str(exc), "ok": False}
    low = (result or "").lower()
    if low.startswith("denied") or "denied by user" in low:
        return {"fact": fact, "category": category, "result": result, "ok": False}
    return {
        "fact": fact,
        "category": category,
        "result": result,
        "ok": True,
    }
