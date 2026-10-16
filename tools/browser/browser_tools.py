"""Agent-facing browser tools. One visible Chromium session per agent run.

Not for general Q&A (use web_research). These tools open and click in a
real window, so CONFIRM gates show the URL or element before anything
happens. Observation text is untrusted and taints the session.
"""

from typing import Optional

from security.gate import Tier, check_permission
from tools.browser.session import BrowserSession
from tools.web.fetch_tools import validate_url
from tools.web.untrusted import one_line, sanitize

_session: BrowserSession | None = None
_last_elements: dict[int, dict] = {}


def get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession(headless=False)
    return _session


def close_session() -> None:
    global _session, _last_elements
    if _session is not None:
        try:
            _session.close()
        finally:
            _session = None
    _last_elements = {}


def _remember(session: BrowserSession) -> None:
    global _last_elements
    _last_elements = dict(session.last_elements)


def browser_open(url: str) -> str:
    validate_url(url)
    check_permission(
        action="browser_open",
        tier=Tier.CONFIRM,
        description=f"Open in browser: {url}",
    )
    session = get_session()
    session.open(url)
    result = session.observe()
    _remember(session)
    return result


def browser_observe(looking_for: Optional[str] = None) -> str:
    check_permission(
        action="browser_observe",
        tier=Tier.AUTO_ALLOW,
        description=(
            f"Re-read the current browser page"
            + (f" (looking for: {looking_for})" if looking_for else "")
        ),
    )
    session = get_session()
    result = session.observe(looking_for=looking_for)
    _remember(session)
    return result


def browser_click(ref: int) -> str:
    if isinstance(ref, bool) or not isinstance(ref, int):
        raise ValueError(f"ref must be an integer, got {ref!r}")
    if ref not in _last_elements:
        raise ValueError(
            f"No element with ref {ref} in the most recent observation. "
            "Call browser_observe first and use a ref from that result."
        )
    element = _last_elements[ref]
    name = one_line(sanitize(element.get("name") or ""))
    href_raw = element.get("href")
    if href_raw:
        href_shown = one_line(sanitize(str(href_raw)))
    else:
        href_shown = "none (not a link)"
    session = get_session()
    current_url = session.page.url
    role = one_line(sanitize(str(element.get("role") or "")))
    description = (
        f"Click on page: {current_url}\n"
        f"Element [{ref}] {role}, label supplied by the page: \"{name}\"\n"
        f"Link target: {href_shown}"
    )
    check_permission(
        action="browser_click",
        tier=Tier.CONFIRM,
        description=description,
    )
    session.click(ref)
    result = session.observe()
    _remember(session)
    return result
