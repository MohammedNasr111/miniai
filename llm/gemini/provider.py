"""Google Gemini provider via the official OpenAI-compatible endpoint.

Only host: generativelanguage.googleapis.com
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests

from llm.base import ChatMessage, ChatResponse, LLMProvider
from security.gemini_key import load_key, mark_rejected

logger = logging.getLogger(__name__)

ALLOWED_HOST = "generativelanguage.googleapis.com"
DEFAULT_BASE_URL = f"https://{ALLOWED_HOST}/v1beta/openai"
QUOTA_MESSAGE = (
    "Gemini's free limit is used up for now. Answering on this PC instead."
)

# Module-level: last Flash model chosen for the UI rail.
_last_chosen_model: str = ""


def last_chosen_model_name() -> str:
    return _last_chosen_model


class GeminiQuotaError(RuntimeError):
    """429 / free-tier exhausted — caller should fall back to local."""


class GeminiAuthError(RuntimeError):
    """Key rejected by Google."""


class GeminiConfigError(ValueError):
    """Refused base URL or missing key."""


def assert_allowed_base_url(base_url: str) -> str:
    """Refuse any host other than the official Gemini API host."""
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        raise GeminiConfigError("empty Gemini base URL")
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = (parsed.hostname or "").lower()
    if host != ALLOWED_HOST:
        raise GeminiConfigError(
            f"Gemini provider refuses host {host!r}; only {ALLOWED_HOST} is allowed"
        )
    if parsed.scheme and parsed.scheme.lower() != "https":
        raise GeminiConfigError("Gemini provider requires https")
    return raw


def _pick_flash_model(models: list[str]) -> str:
    """Prefer a free-tier Flash-class model from the account's list."""
    # Strip optional "models/" prefix
    names = [m.split("/")[-1] for m in models if m]
    flash = [n for n in names if re.search(r"(?i)flash", n) and "embed" not in n.lower()]
    # Prefer newer flash (lexicographic on version-ish tokens is weak; rank known prefs)
    # Prefer stable aliases first — numbered previews (e.g. 3.8) often 503
    # under free-tier load while *-latest / *-lite-latest still answer.
    prefs = (
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    )
    lower_map = {n.lower(): n for n in flash}
    for p in prefs:
        if p in lower_map:
            return lower_map[p]
    # Any flash with -lite last
    non_lite = [n for n in flash if "lite" not in n.lower()]
    if non_lite:
        return sorted(non_lite, reverse=True)[0]
    if flash:
        return sorted(flash, reverse=True)[0]
    if names:
        return names[0]
    return "gemini-2.0-flash"


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 90.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = assert_allowed_base_url(base_url or DEFAULT_BASE_URL)
        key = (api_key if api_key is not None else load_key()) or ""
        if not key.strip():
            raise GeminiConfigError("No Gemini API key configured")
        self._api_key = key.strip()
        self.timeout = timeout
        self._session = session or requests.Session()
        self.model = model or self._resolve_model()
        global _last_chosen_model
        _last_chosen_model = self.model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _resolve_model(self) -> str:
        try:
            url = f"{self.base_url}/models"
            r = self._session.get(url, headers=self._headers(), timeout=min(30.0, self.timeout))
            if r.status_code in (401, 403):
                mark_rejected()
                raise GeminiAuthError("Key rejected by Google")
            if r.status_code == 429:
                raise GeminiQuotaError(QUOTA_MESSAGE)
            r.raise_for_status()
            data = r.json()
            models: list[str] = []
            if isinstance(data, dict):
                for item in data.get("data") or data.get("models") or []:
                    if isinstance(item, dict):
                        mid = item.get("id") or item.get("name") or ""
                        if mid:
                            models.append(str(mid))
                    elif isinstance(item, str):
                        models.append(item)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("id"):
                        models.append(str(item["id"]))
            chosen = _pick_flash_model(models)
            logger.info("gemini model chosen=%s from %s candidates", chosen, len(models))
            return chosen
        except (GeminiAuthError, GeminiQuotaError, GeminiConfigError):
            raise
        except Exception as exc:
            logger.warning("gemini model list failed (%s); using fallback flash id", type(exc).__name__)
            return "gemini-2.0-flash"

    def _build_payload(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]],
        kwargs: dict[str, Any],
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream"] = True
        # Drop Lemonade-only kwargs that Gemini rejects
        kwargs.pop("enable_thinking", None)
        kwargs.pop("chat_template_kwargs", None)
        payload.update(kwargs)
        return payload

    def _handle_http_error(self, response: requests.Response) -> None:
        code = response.status_code
        if code in (401, 403):
            mark_rejected()
            raise GeminiAuthError("Key rejected by Google")
        if code == 429:
            raise GeminiQuotaError(QUOTA_MESSAGE)
        response.raise_for_status()

    def _post_once(
        self,
        payload: dict[str, Any],
        *,
        stream: bool,
        timeout: float,
    ) -> requests.Response:
        # Re-assert host on every call (defence in depth).
        assert_allowed_base_url(self.base_url)
        url = f"{self.base_url}/chat/completions"
        return self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=timeout,
            stream=stream,
        )

    def _post_with_retry(
        self,
        payload: dict[str, Any],
        *,
        stream: bool = False,
        timeout: float | None = None,
    ) -> requests.Response:
        """One retry on timeout/5xx; never retry 429 in a loop."""
        t = timeout if timeout is not None else self.timeout
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                resp = self._post_once(payload, stream=stream, timeout=t)
                if resp.status_code == 429:
                    self._handle_http_error(resp)
                if resp.status_code >= 500 and attempt == 0:
                    logger.warning("gemini 5xx %s; retrying once", resp.status_code)
                    continue
                self._handle_http_error(resp)
                return resp
            except GeminiQuotaError:
                raise
            except GeminiAuthError:
                raise
            except requests.Timeout as exc:
                last_exc = exc
                if attempt == 0:
                    logger.warning("gemini timeout; retrying once")
                    continue
                raise
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == 0:
                    logger.warning("gemini request error; retrying once: %s", type(exc).__name__)
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError("gemini request failed")

    def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        timeout = float(kwargs.pop("timeout", self.timeout))
        payload = self._build_payload(messages, tools, kwargs, stream=False)
        # Capture for footprint (no secrets)
        self.last_request_meta = {
            "model": self.model,
            "message_chars": sum(len(m.content or "") for m in messages),
            "tool_count": len(tools or []),
            "host": ALLOWED_HOST,
        }
        resp = self._post_with_retry(payload, stream=False, timeout=timeout)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return ChatResponse(
            content=message.get("content", "") or "",
            finish_reason=choice.get("finish_reason"),
            tool_calls=message.get("tool_calls"),
            raw=data,
        )

    def chat_stream(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        on_token: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        from llm.lemonade.provider import StreamCancelled

        timeout = float(kwargs.pop("timeout", self.timeout))
        payload = self._build_payload(messages, tools, kwargs, stream=True)
        self.last_request_meta = {
            "model": self.model,
            "message_chars": sum(len(m.content or "") for m in messages),
            "tool_count": len(tools or []),
            "host": ALLOWED_HOST,
        }
        content_parts: list[str] = []
        tool_acc: dict[int, dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        raw_chunks = 0

        resp = self._post_with_retry(payload, stream=True, timeout=timeout)
        try:
            for raw_line in resp.iter_lines(decode_unicode=True):
                if cancel_check is not None and cancel_check():
                    raise StreamCancelled("".join(content_parts))
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                raw_chunks += 1
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice0 = choices[0]
                fr = choice0.get("finish_reason")
                if fr:
                    finish_reason = fr
                delta = choice0.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    if on_token is not None:
                        on_token(piece)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_acc.setdefault(
                        idx,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    if tc.get("type"):
                        slot["type"] = tc["type"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = (
                            slot["function"].get("name") or ""
                        ) + fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] = (
                            slot["function"].get("arguments") or ""
                        ) + fn["arguments"]
        finally:
            resp.close()

        tool_calls: Optional[list[dict[str, Any]]] = None
        if tool_acc:
            tool_calls = [tool_acc[i] for i in sorted(tool_acc)]
        return ChatResponse(
            content="".join(content_parts),
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            raw={"stream_chunks": raw_chunks, "stream": True, "model": self.model},
        )


# Attribute for footprint capture (set on instances in chat/chat_stream).
GeminiProvider.last_request_meta = {}  # type: ignore[attr-defined]
