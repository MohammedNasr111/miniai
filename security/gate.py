"""Permission gate: every tool call in this project must route through
check_permission() before touching the filesystem, network, or system.
Tiers, per ARCHITECTURE.md's security section:
  AUTO_ALLOW      - read, search, web search
  CONFIRM         - create/modify files, terminal commands
  ALWAYS_CONFIRM  - delete files, install software, run unknown executables
"""

from enum import Enum


class Tier(Enum):
    AUTO_ALLOW = "auto_allow"
    CONFIRM = "confirm"
    ALWAYS_CONFIRM = "always_confirm"


class PermissionDenied(Exception):
    pass


def check_permission(action: str, tier: Tier, description: str) -> None:
    """Enforce the permission tier for one action.
    AUTO_ALLOW returns immediately. CONFIRM and ALWAYS_CONFIRM print the
    description and require an explicit "yes" (case-insensitive) typed
    at the prompt; anything else raises PermissionDenied. There is no
    "remember my choice" option yet, by design — every CONFIRM and
    ALWAYS_CONFIRM action asks every time until we decide otherwise.
    """
    if tier == Tier.AUTO_ALLOW:
        return
    print(f"\n[PERMISSION REQUIRED - {tier.value.upper()}]")
    print(f"Action: {action}")
    print(description)
    answer = input("Allow? [yes/no]: ").strip().lower()
    if answer != "yes":
        raise PermissionDenied(f"User denied: {action}")
