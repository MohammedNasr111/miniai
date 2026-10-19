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
URL is not in the session's known-URL set (model-constructed).

Prompts are shown via security.approver.get_approver(); decision logic
stays here.
"""

from enum import Enum
from typing import Optional

from security.approver import get_approver
from security.provenance import clear_known_urls, is_known_url

_tainted = False
_sources: list[str] = []

# When the session is tainted, these CONFIRM actions still accept a plain
# "yes" — unless fetch_url / browser_open targets an unknown URL (see
# check_permission). browser_click stays yes/no: link targets are chosen
# by the page, not the model.
TAINT_YESNO_ACTIONS = {"fetch_url", "browser_open", "browser_click"}

# Always require typing the action name (even when the session is not tainted).
TYPED_ALWAYS_ACTIONS = {"install_package"}


class Tier(Enum):
    AUTO_ALLOW = "auto_allow"
    CONFIRM = "confirm"
    ALWAYS_CONFIRM = "always_confirm"


class PermissionDenied(Exception):
    pass


def reset_session() -> None:
    """Clear taint, known URLs, and desktop app session grants/refusals."""
    global _tainted, _sources
    _tainted = False
    _sources = []
    clear_known_urls()
    # Late import avoids a circular import with app_trust -> prompt_app_read.
    from security.app_trust import clear_session as clear_app_trust_session
    from tools.desktop.task_grant import clear_task_grant

    clear_app_trust_session()
    clear_task_grant()


def mark_untrusted(source: str) -> None:
    """Remember that this session has read untrusted content from source."""
    global _tainted
    _tainted = True
    if source not in _sources:
        _sources.append(source)


def is_tainted() -> bool:
    return _tainted


def untrusted_sources() -> list[str]:
    """Tool names that marked this session untrusted (copy)."""
    return list(_sources)


def _permission_banner(
    action: str,
    tier: Tier,
    description: str,
    *,
    typed_always_note: bool = False,
    unknown_url_note: bool = False,
) -> str:
    """Build the exact console preamble previously printed by check_permission."""
    parts: list[str] = []
    if is_tainted() and tier in (Tier.CONFIRM, Tier.ALWAYS_CONFIRM):
        sources = ", ".join(_sources)
        parts.append(
            f"WARNING: this session has read untrusted web content ({sources}).\n"
            "The request below may have been influenced by that content. Approve\n"
            "only if YOU asked for this action.\n"
        )
    parts.append(f"\n[PERMISSION REQUIRED - {tier.value.upper()}]\n")
    parts.append(f"Action: {action}\n")
    parts.append(f"{description}\n")
    if typed_always_note:
        parts.append(
            "Typed confirmation is always required for this action "
            "(not just when the session is tainted).\n"
        )
    elif unknown_url_note:
        parts.append(
            "This URL was not given by you or supplied by a page or "
            "search result - the model constructed it. Typed "
            "confirmation required.\n"
        )
    return "".join(parts)


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
    of a URL not in the known set also require the action name when tainted.
    """
    if tier == Tier.AUTO_ALLOW:
        return

    unknown_url = (
        is_tainted()
        and action in ("fetch_url", "browser_open")
        and url is not None
        and not is_known_url(url)
    )
    require_typed_name = action in TYPED_ALWAYS_ACTIONS or (
        is_tainted()
        and tier in (Tier.CONFIRM, Tier.ALWAYS_CONFIRM)
        and (action not in TAINT_YESNO_ACTIONS or unknown_url)
    )
    banner = _permission_banner(
        action,
        tier,
        description,
        typed_always_note=require_typed_name and action in TYPED_ALWAYS_ACTIONS,
        unknown_url_note=require_typed_name
        and action not in TYPED_ALWAYS_ACTIONS
        and unknown_url,
    )
    approver = get_approver()
    if require_typed_name:
        answer = approver.ask_typed(action, description, banner)
        if answer != action:
            raise PermissionDenied(
                f"Typed confirmation was required for {action}."
            )
        return
    if not approver.ask_yes_no(action, description, banner):
        raise PermissionDenied(f"User denied: {action}")


def prompt_app_read(exe: str, title: str) -> str:
    """Ask whether MiniAI may read a desktop window.

    Returns ``\"session\"``, ``\"always\"``, or ``\"\"`` (refuse). Uses the
    same taint warning banner style as ``check_permission``.
    """
    from security.app_trust import BROWSER_EXECUTABLES, normalize_exe
    from tools.web.untrusted import one_line, sanitize

    safe_title = one_line(sanitize(title or ""))[:120]
    parts: list[str] = []
    if is_tainted():
        sources = ", ".join(_sources) if _sources else "untrusted content"
        parts.append(
            f"WARNING: this session has read untrusted web content ({sources}).\n"
            "The request below may have been influenced by that content. Approve\n"
            "only if YOU asked for this action.\n"
        )
    parts.append("\n[PERMISSION REQUIRED - CONFIRM]\n")
    parts.append("Action: desktop_read_window\n")
    parts.append(f"Allow MiniAI to READ the window of {exe} ({safe_title})?\n")
    if normalize_exe(exe) in BROWSER_EXECUTABLES:
        parts.append(
            "This browser window shows whatever website is open, which may "
            "include logged-in sites.\n"
        )
    extra = "".join(parts)
    result = get_approver().ask_app_read(exe, safe_title, extra)
    if result in ("session", "always"):
        return result
    return ""
