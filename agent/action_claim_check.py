"""Honesty check: action claims in the final answer must match successful tools."""

from __future__ import annotations

import re
from typing import Any, Optional

# First-person past / present-perfect (and "I'll remember") claims → required tools.
_CLAIM_SPECS: list[tuple[str, re.Pattern[str], frozenset[str]]] = [
    (
        "remembered / saved to memory",
        re.compile(
            r"(?i)\b(?:i(?:'ll|\s+will)\s+remember|"
            r"i(?:'ve|\s+have)\s+remembered|"
            r"i\s+remembered|"
            r"i(?:'ve|\s+have)\s+saved\s+(?:that\s+|it\s+)?to\s+memory|"
            r"i(?:'ve|\s+have)\s+noted|"
            r"i\s+noted\s+(?:that|it))\b"
        ),
        frozenset({"save_memory"}),
    ),
    (
        "deleted / moved to Recycle Bin",
        re.compile(
            r"(?i)\b(?:i(?:'ve|\s+have)\s+(?:deleted|removed)|"
            r"i\s+(?:deleted|removed)|"
            r"i(?:'ve|\s+have)\s+moved\s+(?:them|it|[^.]*?)\s+to\s+(?:the\s+)?recycle\s+bin|"
            r"i\s+moved\s+(?:them|it|[^.]*?)\s+to\s+(?:the\s+)?recycle\s+bin)\b"
        ),
        frozenset({"delete_file"}),
    ),
    (
        "moved / organised / renamed",
        re.compile(
            r"(?i)\b(?:i(?:'ve|\s+have)\s+(?:moved|organised|organized|renamed)|"
            r"i\s+(?:moved|organised|organized|renamed))\b"
        ),
        frozenset({"move_file"}),
    ),
    (
        "created / wrote a file",
        re.compile(
            r"(?i)\b(?:i(?:'ve|\s+have)\s+(?:created|written|wrote|saved)\s+(?:the\s+)?"
            r"(?:file|document|note|folder)|"
            r"i\s+(?:created|wrote|saved)\s+(?:the\s+)?(?:file|document|note)|"
            r"i(?:'ve|\s+have)\s+saved\s+the\s+file)\b"
        ),
        frozenset({"create_file", "write_file", "ws_write", "ws_edit"}),
    ),
    (
        "typed / entered into an app",
        re.compile(
            r"(?i)\b(?:i(?:'ve|\s+have)\s+(?:typed|entered|inserted)|"
            r"i\s+(?:typed|entered|inserted))\b"
        ),
        frozenset({"desktop_set_text", "desktop_insert_text"}),
    ),
    (
        "installed a package",
        re.compile(
            r"(?i)\b(?:i(?:'ve|\s+have)\s+installed|i\s+installed)\b"
        ),
        frozenset({"install_package"}),
    ),
]

_REMEMBER_INTENT = re.compile(
    r"(?i)\b(?:remember|don't\s+forget|do\s+not\s+forget|note\s+that|"
    r"keep\s+in\s+mind|save\s+this|save\s+that)\b"
)

# Asking what was stored — must actually call a memory read tool this turn.
# Do NOT match "Remember my favourite colour is …" (that is save-intent).
_RECALL_INTENT = re.compile(
    r"(?i)\b(?:what(?:'s|\s+is|\s+was)?\s+my\b|"
    r"do\s+you\s+remember\b|what\s+do\s+you\s+remember\b)\b"
)
_RECALL_TOOLS = frozenset({"search_memory", "list_memories"})

RERUN_SYSTEM_NOTE = (
    "The previous draft claimed an action that wasn't performed. "
    "Perform it with the correct tool, or say plainly that it wasn't done."
)

RERUN_RECALL_NOTE = (
    "The user asked what you remember. Call search_memory (or list_memories) "
    "before answering; do not rely only on earlier context."
)

CORRECTION_TMPL = (
    "\n\n⚠ Correction: I said I {claim}, but that didn't actually happen."
)

# Cleared each turn in run_tool_rounds.
_succeeded_tools: set[str] = set()
_denied_tools: set[str] = set()
_failed_tools: set[str] = set()


def reset_action_claim_state() -> None:
    _succeeded_tools.clear()
    _denied_tools.clear()
    _failed_tools.clear()


def get_succeeded_tools() -> set[str]:
    return set(_succeeded_tools)


def record_tool_outcome(name: str, result_text: str) -> str:
    """Classify and record a tool result. Returns outcome: ok|denied|failed."""
    if not name:
        return "failed"
    text = result_text or ""
    low = text.lower()
    if (
        text.startswith("Denied")
        or "denied by user" in low
        or low.startswith("denied:")
    ):
        _denied_tools.add(name)
        return "denied"
    if (
        text.startswith("Error:")
        or text.startswith("REFUSED:")
        or text.startswith("NOT DONE:")
        or "blocked duplicate" in low
        or text.startswith("Blocked")
    ):
        _failed_tools.add(name)
        return "failed"
    _succeeded_tools.add(name)
    return "ok"


def user_has_remember_intent(user_text: str) -> bool:
    return bool(_REMEMBER_INTENT.search(user_text or ""))


def find_unbacked_claims(
    answer: str,
    succeeded: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Return claim dicts that are not backed by a successful matching tool."""
    if succeeded is None:
        succeeded = _succeeded_tools
    found: list[dict[str, Any]] = []
    text = answer or ""
    for label, pattern, tools in _CLAIM_SPECS:
        if not pattern.search(text):
            continue
        if succeeded & tools:
            continue
        found.append({"claim": label, "tools": sorted(tools), "backed": False})
    return found


def remember_intent_unsatisfied(
    user_text: str,
    succeeded: Optional[set[str]] = None,
) -> bool:
    if succeeded is None:
        succeeded = _succeeded_tools
    return user_has_remember_intent(user_text) and "save_memory" not in succeeded


def user_has_recall_intent(user_text: str) -> bool:
    return bool(_RECALL_INTENT.search(user_text or ""))


def recall_intent_unsatisfied(
    user_text: str,
    succeeded: Optional[set[str]] = None,
) -> bool:
    if succeeded is None:
        succeeded = _succeeded_tools
    if not user_has_recall_intent(user_text):
        return False
    return not (succeeded & _RECALL_TOOLS)


def needs_action_claim_fix(
    answer: str,
    user_text: str,
    succeeded: Optional[set[str]] = None,
) -> tuple[bool, list[dict[str, Any]], bool]:
    """Return (needs_fix, unbacked_claims, remember_gap).

    remember_gap is True for save-intent without save_memory OR recall-intent
    without search_memory/list_memories.
    """
    if succeeded is None:
        succeeded = _succeeded_tools
    unbacked = find_unbacked_claims(answer, succeeded)
    remember_gap = remember_intent_unsatisfied(
        user_text, succeeded
    ) or recall_intent_unsatisfied(user_text, succeeded)
    return bool(unbacked) or remember_gap, unbacked, remember_gap


def format_correction(unbacked: list[dict[str, Any]], remember_gap: bool) -> str:
    if unbacked:
        claim = unbacked[0]["claim"]
    elif remember_gap:
        claim = "remembered / saved to memory"
    else:
        claim = "completed that action"
    # Short verb phrase for the template
    short = claim.split("/")[0].strip()
    return CORRECTION_TMPL.format(claim=short)


def apply_action_claim_correction(
    answer: str,
    user_text: str,
    succeeded: Optional[set[str]] = None,
    transcript: Any = None,
    *,
    reran: bool = False,
) -> tuple[str, dict[str, Any]]:
    """If claims still unbacked after optional re-run, append a correction."""
    if succeeded is None:
        succeeded = _succeeded_tools
    needs, unbacked, remember_gap = needs_action_claim_fix(
        answer, user_text, succeeded
    )
    detail = {
        "fired": needs,
        "reran": reran,
        "unbacked": unbacked,
        "remember_gap": remember_gap,
        "succeeded": sorted(succeeded),
        "denied": sorted(_denied_tools),
        "correction_appended": False,
    }
    if not needs:
        if transcript is not None:
            try:
                transcript.write("action_claim_check", **detail)
            except Exception:
                pass
        return answer, detail
    note = format_correction(unbacked, remember_gap)
    new_answer = (answer or "").rstrip()
    if "⚠ Correction: I said I" not in new_answer:
        new_answer = new_answer + note
        detail["correction_appended"] = True
    if transcript is not None:
        try:
            transcript.write("action_claim_check", **detail)
        except Exception:
            pass
    return new_answer, detail
