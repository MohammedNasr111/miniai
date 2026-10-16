"""Agent-facing browser tools. One visible Chromium session per agent run.

Not for general Q&A (use web_research). These tools open and click in a
real window, so CONFIRM gates show the URL or element before anything
happens. Observation text is untrusted and taints the session.
"""

import re
from typing import Optional
from urllib.parse import urlparse

from security.gate import Tier, check_permission
from tools.browser.session import BrowserSession
from tools.web.fetch_tools import validate_url
from tools.web.untrusted import one_line, sanitize
from tools.web.url_display import describe_url

_session: BrowserSession | None = None
_last_elements: dict[int, dict] = {}

_SENSITIVE_NAME_RE = re.compile(r"(pass|pwd|card|cvv|cvc|iban)", re.IGNORECASE)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REFUSAL_SENSITIVE = (
    "MiniAI does not type passwords or payment details; "
    "the user must type these themselves in the browser window."
)


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


def _origin_of(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return one_line(sanitize(url or "")) or "(unknown)"


def browser_open(url: str) -> str:
    validate_url(url)
    check_permission(
        action="browser_open",
        tier=Tier.CONFIRM,
        description=f"Open in browser:\n{describe_url(url)}",
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
        href_shown = describe_url(str(href_raw))
    else:
        href_shown = "none (not a link)"
    session = get_session()
    current_url = session.page.url
    role = one_line(sanitize(str(element.get("role") or "")))
    description = (
        f"Click on page: {one_line(sanitize(current_url))}\n"
        f"Element [{ref}] {role}, label supplied by the page: \"{name}\"\n"
        f"Link target: {href_shown}"
    )
    form_action = element.get("formAction")
    form_method = element.get("formMethod")
    if form_action:
        method = one_line(sanitize(str(form_method or "GET")))
        description += (
            f"\nSubmits a form to: {describe_url(str(form_action))} "
            f"(method {method})"
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


def _refuse_sensitive_field(element: dict) -> None:
    input_type = (element.get("inputType") or "").lower()
    autocomplete = (element.get("autocomplete") or "").lower()
    name_attr = element.get("nameAttr") or ""
    id_attr = element.get("idAttr") or ""
    if input_type == "password":
        raise ValueError(_REFUSAL_SENSITIVE)
    if "password" in autocomplete or autocomplete.startswith("cc-"):
        raise ValueError(_REFUSAL_SENSITIVE)
    if _SENSITIVE_NAME_RE.search(name_attr) or _SENSITIVE_NAME_RE.search(id_attr):
        raise ValueError(_REFUSAL_SENSITIVE)


def _validate_type_text(text: str) -> None:
    if not isinstance(text, str):
        raise ValueError(f"text must be a string, got {type(text).__name__}")
    if len(text) > 500:
        raise ValueError("text must be at most 500 characters")
    if _CONTROL_CHAR_RE.search(text):
        raise ValueError(
            "text must not contain control characters other than newline"
        )


def browser_type(ref: int, text: str) -> str:
    if isinstance(ref, bool) or not isinstance(ref, int):
        raise ValueError(f"ref must be an integer, got {ref!r}")
    if ref not in _last_elements:
        raise ValueError(
            f"No element with ref {ref} in the most recent observation. "
            "Call browser_observe first and use a ref from that result."
        )
    element = _last_elements[ref]
    role = element.get("role") or ""
    if role != "textbox":
        raise ValueError(
            f"ref {ref} has role {role!r}; browser_type requires role "
            "'textbox'."
        )
    _refuse_sensitive_field(element)
    _validate_type_text(text)

    name = one_line(sanitize(element.get("name") or ""))
    session = get_session()
    current_url = session.page.url
    origin = _origin_of(current_url)
    shown_text = text.replace("\n", "\\n")
    description = (
        f"Type into page: {origin} ({describe_url(current_url)})\n"
        f"Field [{ref}] textbox, label supplied by the page: \"{name}\"\n"
        f"Text to type ({len(text)} characters):\n"
        f"{shown_text}\n"
        "WARNING: this site can read the text as soon as it is typed, even if\n"
        "nothing is submitted."
    )
    check_permission(
        action="browser_type",
        tier=Tier.CONFIRM,
        description=description,
    )
    session.type_text(ref, text)
    result = session.observe()
    _remember(session)
    return result
