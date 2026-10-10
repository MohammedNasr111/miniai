"""Blocks identical tool calls within a single agent run.

One CallGuard per run. Mutating calls (CONFIRM / ALWAYS_CONFIRM) are
never repeated. Read-only calls (AUTO_ALLOW) may be repeated only after
a mutating call has succeeded, which clears the read-only memory.
"""

import json
from typing import Any, Optional

from security.gate import Tier
from tools.registry import TOOL_TIERS

_MUTATING = {Tier.CONFIRM, Tier.ALWAYS_CONFIRM}

_BLOCK = (
    "Blocked duplicate call: {name} was already called with these exact\n"
    "arguments in this session. Its result is earlier in the conversation.\n"
    "Do not repeat this call; use the earlier result or change approach."
)


def _fingerprint(name: str, args: Any) -> tuple[str, str]:
    """(tool_name, canonical args). Unparseable argument strings stay raw."""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return (name, args)
        return (name, json.dumps(parsed, sort_keys=True))
    return (name, json.dumps(args, sort_keys=True))


class CallGuard:
    def __init__(self) -> None:
        self._mutating_attempted: set[tuple[str, str]] = set()
        self._readonly_since_mutation: set[tuple[str, str]] = set()

    def check(self, name: str, args: Any) -> Optional[str]:
        """None if the call may run, otherwise the block message."""
        tier = TOOL_TIERS.get(name)
        if tier is None:
            return None
        fp = _fingerprint(name, args)
        if tier in _MUTATING:
            if fp in self._mutating_attempted:
                return _BLOCK.format(name=name)
            return None
        if fp in self._readonly_since_mutation:
            return _BLOCK.format(name=name)
        return None

    def record(self, name: str, args: Any, succeeded: bool) -> None:
        """Remember a call that actually ran. A blocked call is not recorded."""
        tier = TOOL_TIERS.get(name)
        if tier is None:
            return
        fp = _fingerprint(name, args)
        if tier in _MUTATING:
            self._mutating_attempted.add(fp)
            if succeeded:
                self._readonly_since_mutation.clear()
            return
        self._readonly_since_mutation.add(fp)
