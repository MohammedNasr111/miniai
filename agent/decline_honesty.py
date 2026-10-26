"""Honest wording when the user declined the only mutating action."""

from __future__ import annotations

import re
from typing import Any, Optional

from agent.action_claim_check import get_denied_tools, get_succeeded_tools

_MUTATING = frozenset(
    {
        "create_file",
        "create_folder",
        "write_file",
        "delete_file",
        "move_file",
        "move_files",
        "ws_write",
        "ws_edit",
        "run_file",
        "run_code",
        "run_tests",
        "install_package",
        "save_memory",
        "workspace_import",
        "workspace_export",
        "workspace_restore",
    }
)

_DECLINE_PREFIX = "You declined, so nothing was changed."

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def only_mutating_was_denied(
    denied: Optional[set[str]] = None,
    succeeded: Optional[set[str]] = None,
) -> bool:
    """True when ≥1 mutating tool was denied and none of those mutating tools succeeded."""
    if denied is None:
        denied = get_denied_tools()
    if succeeded is None:
        succeeded = get_succeeded_tools()
    denied_m = denied & _MUTATING
    if not denied_m:
        return False
    # Any successful mutating tool means something did change.
    if succeeded & _MUTATING:
        return False
    return True


def apply_decline_wording(
    answer: str,
    *,
    denied: Optional[set[str]] = None,
    succeeded: Optional[set[str]] = None,
) -> tuple[str, Optional[dict[str, Any]]]:
    """Replace the first sentence when the user declined the only mutation(s)."""
    if not only_mutating_was_denied(denied=denied, succeeded=succeeded):
        return answer, None
    text = (answer or "").strip()
    if not text:
        return _DECLINE_PREFIX, {"corrected": True, "reason": "empty"}
    if text.startswith(_DECLINE_PREFIX):
        return text, {"corrected": False, "already": True}
    parts = _SENTENCE_SPLIT.split(text, maxsplit=1)
    remainder = parts[1].strip() if len(parts) > 1 else ""
    if remainder:
        fixed = f"{_DECLINE_PREFIX} {remainder}"
    else:
        fixed = _DECLINE_PREFIX
    return fixed, {"corrected": True, "reason": "user_declined"}
