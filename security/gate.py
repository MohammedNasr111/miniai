"""Permission gate: every tool call in this project must route through
check_permission() before touching the filesystem, network, or system.
Tiers, per ARCHITECTURE.md's security section:
  AUTO_ALLOW      - read, search, web search
  CONFIRM         - create/modify files, terminal commands
  ALWAYS_CONFIRM  - delete files, install software, run unknown executables

After untrusted web content has been read, CONFIRM and ALWAYS_CONFIRM
actions other than those in TAINT_YESNO_ACTIONS require the user to type
the action name. Untainted sessions still accept "yes". For fetch_url and
browser_open, a tainted session also requires the action name when the
URL carries data (query, fragment, or a path that changes when decoded).
"""

from enum import Enum
from typing import Optional

from tools.web.url_display import carries_data

_tainted = False
_sources: list[str] = []

# When the session is tainted, these CONFIRM actions still accept a plain
# "yes" — unless fetch_url / browser_open is given a data-carrying URL
# (see check_permission). browser_click stays yes/no: link targets are
# chosen by the page, not the model. They cannot type into fields.
TAINT_YESNO_ACTIONS = {"fetch_url", "browser_open", "browser_click"}


class Tier(Enum):
    AUTO_ALLOW = "auto_allow"
    CONFIRM = "confirm"
    ALWAYS_CONFIRM = "always_confirm"


class PermissionDenied(Exception):
    pass


def reset_session() -> None:
    """Clear taint at the start of an agent run."""
    global _tainted, _sources
    _tainted = False
    _sources = []


def mark_untrusted(source: str) -> None:
    """Remember that this session has read untrusted content from source."""
    global _tainted
    _tainted = True
    if source not in _sources:
        _sources.append(source)


def is_tainted() -> bool:
    return _tainted


def check_permission(
    action: str,
    tier: Tier,
    description: str,
    url: Optional[str] = None,
) -> None:
    """Enforce the permission tier for one action.
    AUTO_ALLOW returns immediately. CONFIRM and ALWAYS_CONFIRM print the
    description and require an explicit "yes" (case-insensitive) typed
    at the prompt; anything else raises PermissionDenied. There is no
    "remember my choice" option yet, by design — every CONFIRM and
    ALWAYS_CONFIRM action asks every time until we decide otherwise.
    Once the session is tainted, the same prompt is shown under a warning,
    and every action except those in TAINT_YESNO_ACTIONS requires the
    action name instead of "yes". Exception: fetch_url and browser_open
    with a data-carrying URL also require the action name when tainted.
    """
    if tier == Tier.AUTO_ALLOW:
        return
    if is_tainted() and tier in (Tier.CONFIRM, Tier.ALWAYS_CONFIRM):
        sources = ", ".join(_sources)
        print(
            f"WARNING: this session has read untrusted web content ({sources}).\n"
            "The request below may have been influenced by that content. Approve\n"
            "only if YOU asked for this action."
        )
    print(f"\n[PERMISSION REQUIRED - {tier.value.upper()}]")
    print(f"Action: {action}")
    print(description)

    data_carrying = (
        is_tainted()
        and action in ("fetch_url", "browser_open")
        and url is not None
        and carries_data(url)
    )
    require_typed_name = (
        is_tainted()
        and tier in (Tier.CONFIRM, Tier.ALWAYS_CONFIRM)
        and (action not in TAINT_YESNO_ACTIONS or data_carrying)
    )
    if require_typed_name:
        if data_carrying:
            print(
                "This URL carries data (shown above). Typed confirmation required."
            )
        answer = input(f"Type {action} to approve, anything else denies: ").strip()
        if answer != action:
            raise PermissionDenied(
                f"Typed confirmation was required for {action}."
            )
        return
    answer = input("Allow? [yes/no]: ").strip().lower()
    if answer != "yes":
        raise PermissionDenied(f"User denied: {action}")
