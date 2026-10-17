"""Blocks identical tool calls within a single agent run.

One CallGuard per run. Mutating calls (CONFIRM / ALWAYS_CONFIRM) that
succeeded or were denied are never repeated. A mutating call that ended
in outcome "error" may be retried once. Read-only calls (AUTO_ALLOW) may
be repeated only after a mutating call has succeeded (which clears the
read-only memory), except that a read-only call ending in "error" is not
recorded, so an identical retry is allowed.
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
        # Mutating: ok/denied — never allow again.
        self._mutating_terminal: set[tuple[str, str]] = set()
        # Mutating: first attempt ended in error — one retry still allowed.
        self._mutating_error_once: set[tuple[str, str]] = set()
        # Mutating: the one allowed retry after error has already been used.
        self._mutating_error_retry_used: set[tuple[str, str]] = set()
        self._readonly_since_mutation: set[tuple[str, str]] = set()

    def check(self, name: str, args: Any) -> Optional[str]:
        """None if the call may run, otherwise the block message."""
        tier = TOOL_TIERS.get(name)
        if tier is None:
            return None
        fp = _fingerprint(name, args)
        if tier in _MUTATING:
            if fp in self._mutating_terminal:
                return _BLOCK.format(name=name)
            if fp in self._mutating_error_retry_used:
                return _BLOCK.format(name=name)
            return None
        if fp in self._readonly_since_mutation:
            return _BLOCK.format(name=name)
        return None

    def record(self, name: str, args: Any, outcome: str) -> None:
        """Remember a call that actually ran. A blocked call is not recorded.

        outcome is \"ok\", \"denied\", or \"error\". Read-only errors are not
        recorded so an identical retry may run. Mutating errors allow one
        retry; a second attempt (any outcome) then blocks further repeats.
        """
        tier = TOOL_TIERS.get(name)
        if tier is None:
            return
        fp = _fingerprint(name, args)
        if tier in _MUTATING:
            if outcome in ("ok", "denied"):
                self._mutating_terminal.add(fp)
                if outcome == "ok":
                    self._readonly_since_mutation.clear()
                return
            if outcome == "error":
                if fp in self._mutating_error_once:
                    self._mutating_error_retry_used.add(fp)
                else:
                    self._mutating_error_once.add(fp)
            return
        # Read-only: do not record errors (retry allowed).
        if outcome == "error":
            return
        self._readonly_since_mutation.add(fp)
