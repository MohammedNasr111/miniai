"""One Chromium page driven by Playwright, with every request checked.

Not registered with the model. Every request in the context goes through
the same address rules as fetch_url (validate_url), decided once per host
for the session. WebSockets use the same host decisions. Service workers
are blocked. Only one page is ever kept: popups and new tabs are closed
as soon as they appear. Dialogs are dismissed. Page-derived text returned
by observe() is sanitized and wrapped as untrusted content. Failures
surface as ValueError, never as a Playwright exception.
"""

import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from tools.web.fetch_tools import validate_url
from tools.web.untrusted import (
    BEGIN_MARKER,
    END_MARKER,
    PREAMBLE,
    one_line,
    sanitize,
)

PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "browser_profile"
NAVIGATION_TIMEOUT_MS = 30_000
CLICK_TIMEOUT_MS = 10_000
SETTLE_TIMEOUT_MS = 5_000
MAX_ELEMENTS = 50
MAX_NAME_CHARS = 80
MAX_TITLE_CHARS = 200
MAX_TEXT_CHARS = 3000
TEXT_LOOKAHEAD_BEFORE = 300
REF_ATTRIBUTE = "data-miniai-ref"

_OBSERVE_JS = """
([maxElements, maxName, refAttr, lookingFor]) => {
  for (const el of document.querySelectorAll('[' + refAttr + ']')) {
    el.removeAttribute(refAttr);
  }
  const selector = 'a[href], button, input, select, textarea, '
    + '[role=button], [role=link], [onclick]';
  const collapse = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const isVisible = (el) => {
    if (el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'hidden') {
      return false;
    }
    if (typeof el.checkVisibility === 'function'
        && !el.checkVisibility({visibilityProperty: true})) {
      return false;
    }
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const roleOf = (el) => {
    const explicit = collapse(el.getAttribute('role'));
    if (explicit) return explicit;
    const tag = el.tagName;
    if (tag === 'A') return 'link';
    if (tag === 'BUTTON') return 'button';
    if (tag === 'SELECT') return 'combobox';
    if (tag === 'TEXTAREA') return 'textbox';
    if (tag === 'INPUT') {
      const type = (el.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox' || type === 'radio') return type;
      return 'textbox';
    }
    return 'clickable';
  };
  const nameOf = (el) => {
    const candidates = [
      el.getAttribute('aria-label'),
      el.innerText,
      el.getAttribute('placeholder'),
      el.value,
      el.getAttribute('title'),
    ];
    for (const candidate of candidates) {
      const text = collapse(typeof candidate === 'string' ? candidate : '');
      if (text) return text.slice(0, maxName);
    }
    return '';
  };

  let scope = null;
  let scopeLabel = 'whole page';
  for (const candidate of document.querySelectorAll('main, [role=main]')) {
    if (isVisible(candidate)) { scope = candidate; scopeLabel = 'main content'; break; }
  }
  if (!scope) {
    for (const candidate of document.querySelectorAll('article')) {
      if (isVisible(candidate)) { scope = candidate; scopeLabel = 'main content'; break; }
    }
  }
  if (!scope) {
    scope = document.body || document.documentElement;
    scopeLabel = 'whole page';
  }

  const allVisible = Array.from(document.querySelectorAll(selector)).filter(isVisible);
  const inScope = [];
  const outScope = [];
  for (const el of allVisible) {
    if (scope.contains(el)) inScope.push(el);
    else outScope.push(el);
  }
  let ordered = inScope.concat(outScope);

  const words = (lookingFor || '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(w => w.length >= 2);
  if (words.length) {
    const scored = ordered.map((el, index) => {
      const hay = (nameOf(el) + ' ' + ((el.tagName === 'A' && el.href) ? el.href : '')).toLowerCase();
      let score = 0;
      for (const word of words) {
        if (hay.includes(word)) score += 1;
      }
      return {el, index, score};
    });
    scored.sort((a, b) => {
      if (a.score !== b.score) return b.score - a.score;
      return a.index - b.index;
    });
    const matched = scored.filter(s => s.score > 0).map(s => s.el);
    const rest = scored.filter(s => s.score === 0).map(s => s.el);
    ordered = matched.concat(rest);
  }

  const items = [];
  for (const el of ordered.slice(0, maxElements)) {
    const ref = items.length + 1;
    el.setAttribute(refAttr, String(ref));
    items.push({
      ref: ref,
      role: roleOf(el),
      name: nameOf(el),
      href: (el.tagName === 'A' && el.href) ? el.href : null,
    });
  }

  const fullText = collapse(scope.innerText || '');
  let textStart = 0;
  let textOffset = false;
  if (words.length && fullText) {
    const lower = fullText.toLowerCase();
    let first = -1;
    for (const word of words) {
      const at = lower.indexOf(word);
      if (at !== -1 && (first === -1 || at < first)) first = at;
    }
    if (first !== -1) {
      textStart = Math.max(0, first - 300);
      textOffset = textStart > 0;
    }
  }
  const text = fullText.slice(textStart, textStart + 3000);
  return {
    total: allVisible.length,
    items: items,
    text: text,
    scopeLabel: scopeLabel,
    textStart: textStart,
    textOffset: textOffset,
  };
}
"""


# Re-read role/name/href on a live element (same rules as _OBSERVE_JS nameOf/roleOf).
_ELEMENT_SNAPSHOT_JS = """
(el, maxName) => {
  if (!el || !el.isConnected) {
    return { detached: true, role: null, name: null, href: null };
  }
  const collapse = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const roleOf = (node) => {
    const explicit = collapse(node.getAttribute('role'));
    if (explicit) return explicit;
    const tag = node.tagName;
    if (tag === 'A') return 'link';
    if (tag === 'BUTTON') return 'button';
    if (tag === 'SELECT') return 'combobox';
    if (tag === 'TEXTAREA') return 'textbox';
    if (tag === 'INPUT') {
      const type = (node.type || 'text').toLowerCase();
      if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
      if (type === 'checkbox' || type === 'radio') return type;
      return 'textbox';
    }
    return 'clickable';
  };
  const nameOf = (node) => {
    const candidates = [
      node.getAttribute('aria-label'),
      node.innerText,
      node.getAttribute('placeholder'),
      node.value,
      node.getAttribute('title'),
    ];
    for (const candidate of candidates) {
      const text = collapse(typeof candidate === 'string' ? candidate : '');
      if (text) return text.slice(0, maxName);
    }
    return '';
  };
  return {
    detached: false,
    role: roleOf(el),
    name: nameOf(el),
    href: (el.tagName === 'A' && el.href) ? el.href : null,
  };
}
"""


def _clean(text: Optional[str]) -> str:
    return sanitize(one_line(text or ""))


def _short(exc: Exception) -> str:
    message = str(exc).strip().splitlines()
    return message[0] if message else type(exc).__name__


def _http_probe_url(url: str) -> str:
    """Rewrite ws/wss to http/https so validate_url can check the host."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme == "ws":
        scheme = "http"
    elif scheme == "wss":
        scheme = "https"
    rebuilt = parsed._replace(scheme=scheme)
    return rebuilt.geturl()


def _changed_element_error(ref: int) -> ValueError:
    return ValueError(
        f"The page changed element [{ref}] since it was observed; "
        "call browser_observe again."
    )


class BrowserSession:
    def __init__(
        self,
        headless: bool = False,
        profile_dir: str | Path | None = None,
    ):
        self.blocked: list[dict] = []
        self.request_log: list[tuple[str, str]] = []
        self.popups: list[str] = []
        self.dialogs: list[dict] = []
        self.last_elements: dict[int, dict] = {}
        self._element_handles: dict[int, object] = {}
        self._host_decisions: dict[str, Optional[str]] = {}
        self._playwright = None
        self._context = None
        self._page = None
        self.profile_dir = Path(profile_dir) if profile_dir is not None else PROFILE_DIR
        try:
            self._playwright = sync_playwright().start()
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=headless,
                accept_downloads=False,
                service_workers="block",
            )
            self._context.route("**/*", self._on_route)
            self._context.route_web_socket("**/*", self._on_websocket)
            pages = list(self._context.pages)
            self._page = pages[0] if pages else self._context.new_page()
            for extra in pages[1:]:
                self.popups.append(extra.url)
                extra.close()
            self._context.on("page", self._on_page)
            self._page.on("dialog", self._on_dialog)
        except PlaywrightError as exc:
            self.close()
            raise ValueError(f"Could not start the browser: {_short(exc)}") from exc

    @property
    def page(self):
        return self._page

    @property
    def context(self):
        return self._context

    def _host_reason(self, host: str, probe_url: str) -> Optional[str]:
        """None if the host may be contacted, otherwise the block reason."""
        if host in self._host_decisions:
            return self._host_decisions[host]
        try:
            validate_url(probe_url)
            reason = None
        except ValueError as exc:
            reason = str(exc)
        self._host_decisions[host] = reason
        return reason

    def _decide(self, url: str) -> Optional[str]:
        """None if the HTTP(S) request may proceed, otherwise the reason."""
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return f"scheme {scheme!r} is not allowed"
        host = (parsed.hostname or "").lower()
        if not host:
            return f"URL has no host: {url!r}"
        return self._host_reason(host, url)

    def _decide_websocket(self, url: str) -> Optional[str]:
        """None if the WebSocket may proceed, otherwise the reason."""
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("ws", "wss"):
            return f"scheme {scheme!r} is not allowed"
        host = (parsed.hostname or "").lower()
        if not host:
            return f"URL has no host: {url!r}"
        return self._host_reason(host, _http_probe_url(url))

    def _on_route(self, route, request) -> None:
        url = request.url
        reason = self._decide(url)
        try:
            if reason is None:
                self.request_log.append((url, "allowed"))
                route.continue_()
            else:
                self.request_log.append((url, "blocked"))
                self.blocked.append({"url": url, "reason": reason})
                route.abort("blockedbyclient")
        except PlaywrightError:
            pass

    def _on_websocket(self, ws) -> None:
        url = ws.url
        reason = self._decide_websocket(url)
        try:
            if reason is None:
                self.request_log.append((url, "allowed"))
                ws.connect_to_server()
                return
            self.request_log.append((url, "blocked"))
            self.blocked.append({"url": url, "reason": reason})
            # Sync ws.close() deadlocks inside a route handler (the close
            # waits for the page, which is waiting for the handler). Schedule
            # the close on the Playwright loop instead.
            impl = ws._impl_obj

            async def _close_blocked() -> None:
                try:
                    await impl.close(code=1008, reason="blocked by MiniAI")
                except Exception:
                    pass

            asyncio.get_event_loop().create_task(_close_blocked())
        except PlaywrightError:
            pass

    def _on_page(self, page) -> None:
        if page is self._page:
            return
        self.popups.append(page.url)
        try:
            page.close()
        except PlaywrightError:
            pass

    def _on_dialog(self, dialog) -> None:
        self.dialogs.append({"type": dialog.type, "message": dialog.message})
        try:
            dialog.dismiss()
        except PlaywrightError:
            pass

    def _require_open(self) -> None:
        if self._page is None or self._page.is_closed():
            raise ValueError("The browser session is closed.")

    def _settle(self) -> None:
        try:
            self._page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            pass
        except PlaywrightError as exc:
            raise ValueError(f"Page did not settle: {_short(exc)}") from exc

    def _release_element_handles(self) -> None:
        for handle in self._element_handles.values():
            try:
                handle.dispose()
            except Exception:
                pass
        self._element_handles = {}

    def open(self, url: str) -> None:
        validate_url(url)
        self._require_open()
        try:
            self._page.goto(
                url,
                timeout=NAVIGATION_TIMEOUT_MS,
                wait_until="domcontentloaded",
            )
        except PlaywrightError as exc:
            raise ValueError(f"Navigation to {url!r} failed: {_short(exc)}") from exc
        self._settle()

    def observe(self, looking_for: Optional[str] = None) -> str:
        self._require_open()
        self._release_element_handles()
        try:
            data = self._page.evaluate(
                _OBSERVE_JS,
                [MAX_ELEMENTS, MAX_NAME_CHARS, REF_ATTRIBUTE, looking_for or ""],
            )
            title = self._page.title()
            current_url = self._page.url
        except PlaywrightError as exc:
            raise ValueError(f"Could not observe the page: {_short(exc)}") from exc

        items = data["items"]
        self.last_elements = {}
        for item in items:
            ref = int(item["ref"])
            meta = {
                "role": item["role"],
                "name": item["name"] or "",
                "href": item["href"],
            }
            self.last_elements[ref] = meta
            # Capture the node itself. data-miniai-ref is only used here to
            # find the just-tagged element; click() uses the stored handle.
            try:
                handle = self._page.evaluate_handle(
                    f"document.querySelector('[{REF_ATTRIBUTE}=\"{ref}\"]')"
                )
            except PlaywrightError as exc:
                raise ValueError(
                    f"Could not hold element ref {ref}: {_short(exc)}"
                ) from exc
            if handle is None:
                raise ValueError(f"Could not hold element ref {ref}: missing handle")
            # evaluate_handle returns a JSHandle; as_element() yields ElementHandle.
            element = handle.as_element()
            if element is None:
                try:
                    handle.dispose()
                except Exception:
                    pass
                raise ValueError(f"Could not hold element ref {ref}: not an element")
            self._element_handles[ref] = element
        scope_label = data["scopeLabel"]
        text_start = int(data.get("textStart") or 0)
        text_offset = bool(data.get("textOffset"))
        if scope_label == "main content":
            if text_offset:
                text_header = (
                    f"Page text ({MAX_TEXT_CHARS} characters from main content, "
                    f"starting at offset {text_start}):"
                )
            else:
                text_header = (
                    f"Page text ({MAX_TEXT_CHARS} characters from main content):"
                )
        else:
            if text_offset:
                text_header = (
                    f"Page text ({MAX_TEXT_CHARS} characters from whole page, "
                    f"starting at offset {text_start}):"
                )
            else:
                text_header = (
                    f"Page text ({MAX_TEXT_CHARS} characters from whole page):"
                )

        lines = list(PREAMBLE)
        lines.append(BEGIN_MARKER)
        lines.append(f"URL: {_clean(current_url)}")
        lines.append(f"Title: {_clean(title)[:MAX_TITLE_CHARS]}")
        lines.append(f"Scope: {scope_label}")
        lines.append(f"Interactive elements ({len(items)} of {data['total']}):")
        for item in items:
            name = _clean(item["name"])[:MAX_NAME_CHARS]
            line = f"[{item['ref']}] {_clean(item['role'])} \"{name}\""
            if item["href"]:
                line += f" -> {_clean(item['href'])}"
            lines.append(line)
        lines.append(text_header)
        lines.append(_clean(data["text"])[:MAX_TEXT_CHARS])
        lines.append(f"Blocked requests this session: {len(self.blocked)}")
        lines.append(END_MARKER)
        return "\n".join(lines)

    def click(self, ref: int) -> None:
        self._require_open()
        if isinstance(ref, bool) or not isinstance(ref, int):
            raise ValueError(f"ref must be an integer, got {ref!r}")
        handle = self._element_handles.get(ref)
        expected = self.last_elements.get(ref)
        if handle is None or expected is None:
            raise ValueError(
                f"No element with ref {ref} in the most recent observation. "
                "Call observe() again and use a ref from that result."
            )
        try:
            snap = handle.evaluate(_ELEMENT_SNAPSHOT_JS, MAX_NAME_CHARS)
        except PlaywrightError as exc:
            raise _changed_element_error(ref) from exc
        if (
            not isinstance(snap, dict)
            or snap.get("detached")
            or snap.get("role") != expected.get("role")
            or (snap.get("name") or "") != (expected.get("name") or "")
            or snap.get("href") != expected.get("href")
        ):
            raise _changed_element_error(ref)
        href = snap.get("href")
        if href and urlparse(href).scheme.lower() in ("http", "https"):
            validate_url(href)
        try:
            handle.click(timeout=CLICK_TIMEOUT_MS)
        except PlaywrightError as exc:
            raise ValueError(f"Click on ref {ref} failed: {_short(exc)}") from exc
        self._settle()

    def close(self) -> None:
        self._release_element_handles()
        self.last_elements = {}
        context, playwright = self._context, self._playwright
        self._page = None
        self._context = None
        self._playwright = None
        try:
            if context is not None:
                context.close()
        except PlaywrightError:
            pass
        finally:
            if playwright is not None:
                try:
                    playwright.stop()
                except PlaywrightError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
