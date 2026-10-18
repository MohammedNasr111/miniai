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
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from security.provenance import remember_url
from tools.web.fetch_tools import extract_text, validate_url
from tools.web.untrusted import (
    BEGIN_MARKER,
    END_MARKER,
    PREAMBLE,
    one_line,
    sanitize,
)

# Cursor/sandbox sometimes points Playwright at an empty cache. Prefer the
# normal user install so agent_loop and tests find Chromium.
_playwright_browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
if "cursor-sandbox-cache" in _playwright_browsers:
    os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)

def _default_profile_dir() -> Path:
    override = os.environ.get("MINIAI_BROWSER_PROFILE", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent.parent / "browser_profile"


PROFILE_DIR = _default_profile_dir()
NAVIGATION_TIMEOUT_MS = 30_000
CLICK_TIMEOUT_MS = 10_000
SETTLE_TIMEOUT_MS = 5_000
MAX_ELEMENTS = 50
MAX_NAME_CHARS = 80
MAX_TITLE_CHARS = 200
MAX_TEXT_CHARS = 3000
START_SECTION_CHARS = 1500
MATCH_LOOKBACK_CHARS = 200
REF_ATTRIBUTE = "data-miniai-ref"

# Dropped when splitting looking_for for element ranking and text match.
_LOOKING_FOR_STOP = frozenset(
    {
        "first",
        "last",
        "sentence",
        "sentences",
        "paragraph",
        "page",
        "article",
        "text",
        "section",
        "heading",
        "the",
        "a",
        "an",
        "of",
        "and",
        "to",
        "in",
        "on",
        "for",
    }
)

# Returns { data: <serializable>, elements: [DOM nodes...] } so handles and
# metadata come from the same evaluation (atomic capture).
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
  const formInfo = (el) => {
    const tag = el.tagName;
    const type = (el.type || '').toLowerCase();
    const isSubmit = (
      (tag === 'BUTTON' && (!type || type === 'submit'))
      || (tag === 'INPUT' && (type === 'submit' || type === 'image'))
    );
    const role = roleOf(el);
    if (isSubmit && el.form) {
      // Prefer formaction/formmethod on the control when present; else the form.
      let action;
      let method;
      if (el.hasAttribute('formaction')) {
        action = el.formAction || el.getAttribute('formaction') || '';
      } else {
        action = el.form.action || '';
      }
      if (el.hasAttribute('formmethod')) {
        method = (el.formMethod || el.getAttribute('formmethod') || 'get').toUpperCase();
      } else {
        method = (el.form.method || 'get').toUpperCase();
      }
      return {
        formAction: action || null,
        formMethod: method || 'GET',
      };
    }
    // Text fields: Enter submits via the form's default submit button
    // (first in tree order); use that button's formaction/formmethod when
    // set, otherwise the form's action/method.
    if (role === 'textbox' && el.form) {
      const form = el.form;
      let defaultBtn = null;
      for (const cand of form.querySelectorAll('button, input')) {
        const cTag = cand.tagName;
        const cType = (cand.type || '').toLowerCase();
        const cSubmit = (
          (cTag === 'BUTTON' && (!cType || cType === 'submit'))
          || (cTag === 'INPUT' && (cType === 'submit' || cType === 'image'))
        );
        if (cSubmit) { defaultBtn = cand; break; }
      }
      if (defaultBtn) {
        let action;
        let method;
        if (defaultBtn.hasAttribute('formaction')) {
          action = defaultBtn.formAction
            || defaultBtn.getAttribute('formaction') || '';
        } else {
          action = form.action || '';
        }
        if (defaultBtn.hasAttribute('formmethod')) {
          method = (defaultBtn.formMethod
            || defaultBtn.getAttribute('formmethod') || 'get').toUpperCase();
        } else {
          method = (form.method || 'get').toUpperCase();
        }
        return {
          formAction: action || null,
          formMethod: method || 'GET',
        };
      }
      return {
        formAction: form.action || null,
        formMethod: (form.method || 'get').toUpperCase() || 'GET',
      };
    }
    return { formAction: null, formMethod: null };
  };
  const fieldMeta = (el) => {
    const tag = el.tagName;
    let inputType = null;
    if (tag === 'INPUT') inputType = (el.type || 'text').toLowerCase();
    else if (tag === 'TEXTAREA') inputType = 'textarea';
    return {
      inputType: inputType,
      autocomplete: el.getAttribute('autocomplete') || '',
      nameAttr: el.getAttribute('name') || '',
      idAttr: el.getAttribute('id') || '',
    };
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
  const elements = [];
  for (const el of ordered.slice(0, maxElements)) {
    const ref = items.length + 1;
    el.setAttribute(refAttr, String(ref));
    const form = formInfo(el);
    const fields = fieldMeta(el);
    items.push({
      ref: ref,
      role: roleOf(el),
      name: nameOf(el),
      href: (el.tagName === 'A' && el.href) ? el.href : null,
      formAction: form.formAction,
      formMethod: form.formMethod,
      inputType: fields.inputType,
      autocomplete: fields.autocomplete,
      nameAttr: fields.nameAttr,
      idAttr: fields.idAttr,
    });
    elements.push(el);
  }

  // Full scope text for Python fallback when trafilatura finds nothing.
  // Keep newlines so sentence/line breaks survive for match excerpts.
  const fullText = (scope.innerText || '').replace(/[ \\t]+/g, ' ')
    .replace(/ ?\\n ?/g, '\\n').trim();
  return {
    data: {
      total: allVisible.length,
      items: items,
      fullText: fullText,
      scopeLabel: scopeLabel,
    },
    elements: elements,
  };
}
"""


# Re-read role/name/href/form on a live element (same rules as observe).
_ELEMENT_SNAPSHOT_JS = """
(el, maxName) => {
  if (!el || !el.isConnected) {
    return {
      detached: true, role: null, name: null, href: null,
      formAction: null, formMethod: null,
    };
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
  const tag = el.tagName;
  const type = (el.type || '').toLowerCase();
  const isSubmit = (
    (tag === 'BUTTON' && (!type || type === 'submit'))
    || (tag === 'INPUT' && (type === 'submit' || type === 'image'))
  );
  const role = roleOf(el);
  let formAction = null;
  let formMethod = null;
  if (isSubmit && el.form) {
    if (el.hasAttribute('formaction')) {
      formAction = el.formAction || el.getAttribute('formaction') || null;
    } else {
      formAction = el.form.action || null;
    }
    if (el.hasAttribute('formmethod')) {
      formMethod = (el.formMethod || el.getAttribute('formmethod') || 'get').toUpperCase();
    } else {
      formMethod = (el.form.method || 'get').toUpperCase();
    }
  } else if (role === 'textbox' && el.form) {
    const form = el.form;
    let defaultBtn = null;
    for (const cand of form.querySelectorAll('button, input')) {
      const cTag = cand.tagName;
      const cType = (cand.type || '').toLowerCase();
      const cSubmit = (
        (cTag === 'BUTTON' && (!cType || cType === 'submit'))
        || (cTag === 'INPUT' && (cType === 'submit' || cType === 'image'))
      );
      if (cSubmit) { defaultBtn = cand; break; }
    }
    if (defaultBtn) {
      if (defaultBtn.hasAttribute('formaction')) {
        formAction = defaultBtn.formAction
          || defaultBtn.getAttribute('formaction') || null;
      } else {
        formAction = form.action || null;
      }
      if (defaultBtn.hasAttribute('formmethod')) {
        formMethod = (defaultBtn.formMethod
          || defaultBtn.getAttribute('formmethod') || 'get').toUpperCase();
      } else {
        formMethod = (form.method || 'get').toUpperCase();
      }
    } else {
      formAction = form.action || null;
      formMethod = (form.method || 'get').toUpperCase() || 'GET';
    }
  }
  return {
    detached: false,
    role: role,
    name: nameOf(el),
    href: (el.tagName === 'A' && el.href) ? el.href : null,
    formAction: formAction,
    formMethod: formMethod,
  };
}
"""


def _clean(text: Optional[str]) -> str:
    return sanitize(one_line(text or ""))


def _short(exc: Exception) -> str:
    message = str(exc).strip().splitlines()
    return message[0] if message else type(exc).__name__


def looking_for_words(looking_for: Optional[str]) -> list[str]:
    """Split looking_for into match tokens, dropping stop words."""
    raw = (looking_for or "").lower()
    parts = []
    buf = []
    for ch in raw:
        if ch.isalnum():
            buf.append(ch)
        else:
            if buf:
                parts.append("".join(buf))
                buf = []
    if buf:
        parts.append("".join(buf))
    return [w for w in parts if len(w) >= 2 and w not in _LOOKING_FOR_STOP]


def _first_match(text: str, words: list[str]) -> tuple[Optional[int], Optional[str]]:
    """Return (index, matched_word) for the earliest case-insensitive hit."""
    if not text or not words:
        return None, None
    lower = text.lower()
    best_at: Optional[int] = None
    best_word: Optional[str] = None
    for word in words:
        at = lower.find(word)
        if at != -1 and (best_at is None or at < best_at):
            best_at = at
            best_word = word
    return best_at, best_word


def _sentence_start(text: str, match_at: int) -> int:
    """Nearest sentence start at or before match, within MATCH_LOOKBACK_CHARS."""
    window_start = max(0, match_at - MATCH_LOOKBACK_CHARS)
    region = text[window_start:match_at]
    best = None
    # ". " boundary: start just after the space.
    pos = 0
    while True:
        found = region.find(". ", pos)
        if found == -1:
            break
        best = window_start + found + 2
        pos = found + 1
    # Line break: start on the next character.
    pos = 0
    while True:
        found = region.find("\n", pos)
        if found == -1:
            break
        cand = window_start + found + 1
        if best is None or cand > best:
            best = cand
        pos = found + 1
    if best is not None:
        return best
    return window_start


def layout_page_text(
    full_text: str, words: list[str], source_label: str
) -> list[str]:
    """Build Page text start / around sections (total budget MAX_TEXT_CHARS)."""
    match_at, matched_word = _first_match(full_text, words)
    need_around = (
        match_at is not None
        and matched_word is not None
        and match_at > START_SECTION_CHARS
    )
    start_budget = START_SECTION_CHARS if need_around else MAX_TEXT_CHARS
    start_chunk = full_text[:start_budget]
    lines = [
        f"Page text - start (up to {start_budget} characters, from {source_label}):",
        _clean(start_chunk)[:start_budget],
    ]
    if need_around:
        assert match_at is not None and matched_word is not None
        begin = _sentence_start(full_text, match_at)
        around = full_text[begin : begin + START_SECTION_CHARS]
        lines.append(
            f"Page text - around '{matched_word}' "
            f"(up to {START_SECTION_CHARS} characters, from {source_label}):"
        )
        lines.append(_clean(around)[:START_SECTION_CHARS])
    return lines


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
        self.close_events: list[dict[str, Any]] = []
        self.last_elements: dict[int, dict] = {}
        self._element_handles: dict[int, object] = {}
        self._observe_root_handle = None
        self._observe_elements_handle = None
        self._host_decisions: dict[str, Optional[str]] = {}
        self._last_open_mono: Optional[float] = None
        self._playwright = None
        self._context = None
        self._page = None
        self.profile_dir = (
            Path(profile_dir) if profile_dir is not None else _default_profile_dir()
        )
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
            self._context.on("close", self._on_context_close)
            self._page.on("dialog", self._on_dialog)
            self._page.on("close", self._on_page_close)
        except PlaywrightError as exc:
            self.close()
            raise ValueError(f"Could not start the browser: {_short(exc)}") from exc

    def is_alive(self) -> bool:
        """True if the Playwright page/context are still open."""
        try:
            if self._page is None or self._context is None:
                return False
            if self._page.is_closed():
                return False
            return True
        except Exception:
            return False

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
        # Credentials are per-URL; do not skip via the per-host cache.
        if parsed.username is not None or parsed.password is not None:
            return "URLs with embedded credentials are not allowed."
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

    def _record_close(self, which: str) -> None:
        now = time.monotonic()
        if self._last_open_mono is None:
            since = None
        else:
            since = round(now - self._last_open_mono, 3)
        self.close_events.append(
            {
                "object": which,
                "closed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "seconds_since_open": since,
            }
        )

    def _on_page_close(self, page) -> None:
        self._record_close("page")

    def _on_context_close(self, context) -> None:
        self._record_close("context")

    def drain_close_events(self) -> list[dict[str, Any]]:
        events = list(self.close_events)
        self.close_events = []
        return events

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
        if self._observe_elements_handle is not None:
            try:
                self._observe_elements_handle.dispose()
            except Exception:
                pass
            self._observe_elements_handle = None
        if self._observe_root_handle is not None:
            try:
                self._observe_root_handle.dispose()
            except Exception:
                pass
            self._observe_root_handle = None

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
        self._last_open_mono = time.monotonic()
        remember_url(self._page.url)

    def observe(self, looking_for: Optional[str] = None) -> str:
        self._require_open()
        self._release_element_handles()
        words = looking_for_words(looking_for)
        # Pass only non-stop words so JS element ranking matches text matching.
        looking_for_filtered = " ".join(words)
        result_handle = None
        try:
            result_handle = self._page.evaluate_handle(
                _OBSERVE_JS,
                [
                    MAX_ELEMENTS,
                    MAX_NAME_CHARS,
                    REF_ATTRIBUTE,
                    looking_for_filtered,
                ],
            )
            data_handle = result_handle.get_property("data")
            data = data_handle.json_value()
            try:
                data_handle.dispose()
            except Exception:
                pass
            elements_handle = result_handle.get_property("elements")
            element_props = elements_handle.get_properties()
            title = self._page.title()
            current_url = self._page.url
            html = self._page.content()
        except PlaywrightError as exc:
            if result_handle is not None:
                try:
                    result_handle.dispose()
                except Exception:
                    pass
            raise ValueError(f"Could not observe the page: {_short(exc)}") from exc

        items = data["items"]
        self.last_elements = {}
        # Handles come from the same evaluation that assigns refs — no
        # follow-up querySelector per ref.
        for item in items:
            ref = int(item["ref"])
            meta = {
                "role": item["role"],
                "name": item["name"] or "",
                "href": item.get("href"),
                "formAction": item.get("formAction"),
                "formMethod": item.get("formMethod"),
                "inputType": item.get("inputType"),
                "autocomplete": item.get("autocomplete") or "",
                "nameAttr": item.get("nameAttr") or "",
                "idAttr": item.get("idAttr") or "",
            }
            self.last_elements[ref] = meta
            if meta.get("href"):
                remember_url(str(meta["href"]))
            if meta.get("formAction"):
                remember_url(str(meta["formAction"]))
            prop = element_props.get(str(ref - 1))
            if prop is None:
                raise ValueError(f"Could not hold element ref {ref}: missing handle")
            element = prop.as_element()
            if element is None:
                try:
                    prop.dispose()
                except Exception:
                    pass
                raise ValueError(f"Could not hold element ref {ref}: not an element")
            self._element_handles[ref] = element
        # Keep result_handle / elements_handle alive: disposing them can
        # invalidate the ElementHandles we just extracted. They are released
        # on the next observe() / close() via _release_element_handles.
        self._observe_root_handle = result_handle
        self._observe_elements_handle = elements_handle
        remember_url(current_url)

        scope_label = data["scopeLabel"]
        fallback_text = data.get("fullText") or ""
        source_label = (
            "main content" if scope_label == "main content" else "whole page"
        )
        full_text = fallback_text
        try:
            _title, extracted = extract_text(html, "text/html")
            if extracted and str(extracted).strip():
                full_text = str(extracted).strip()
                source_label = "article text"
        except ValueError:
            pass

        lines = list(PREAMBLE)
        lines.append(BEGIN_MARKER)
        lines.append(f"URL: {_clean(current_url)}")
        lines.append(f"Title: {_clean(title)[:MAX_TITLE_CHARS]}")
        lines.append(f"Scope: {scope_label}")
        lines.append(f"Interactive elements ({len(items)} of {data['total']}):")
        for item in items:
            name = _clean(item["name"])[:MAX_NAME_CHARS]
            line = f"[{item['ref']}] {_clean(item['role'])} \"{name}\""
            if item.get("href"):
                line += f" -> {_clean(item['href'])}"
            lines.append(line)
        lines.extend(layout_page_text(full_text, words, source_label))
        lines.append(f"Blocked requests this session: {len(self.blocked)}")
        lines.append(END_MARKER)
        return "\n".join(lines)

    def _verify_element(self, ref: int) -> tuple[object, dict]:
        """Return (handle, expected meta) after re-checking the live node."""
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
            or snap.get("formAction") != expected.get("formAction")
            or snap.get("formMethod") != expected.get("formMethod")
        ):
            raise _changed_element_error(ref)
        return handle, expected

    def click(self, ref: int) -> None:
        self._require_open()
        if isinstance(ref, bool) or not isinstance(ref, int):
            raise ValueError(f"ref must be an integer, got {ref!r}")
        handle, expected = self._verify_element(ref)
        href = expected.get("href")
        if href and urlparse(href).scheme.lower() in ("http", "https"):
            validate_url(href)
        try:
            handle.click(timeout=CLICK_TIMEOUT_MS)
        except PlaywrightError as exc:
            raise ValueError(f"Click on ref {ref} failed: {_short(exc)}") from exc
        self._settle()
        remember_url(self._page.url)

    def type_text(self, ref: int, text: str, submit: bool = False) -> None:
        self._require_open()
        if isinstance(ref, bool) or not isinstance(ref, int):
            raise ValueError(f"ref must be an integer, got {ref!r}")
        handle, _expected = self._verify_element(ref)
        try:
            handle.fill(text)
            if submit:
                handle.press("Enter")
        except PlaywrightError as exc:
            raise ValueError(f"Type into ref {ref} failed: {_short(exc)}") from exc
        if submit:
            self._settle()
        remember_url(self._page.url)

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
