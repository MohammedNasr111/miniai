"""Groq OpenAI-compatible provider — planner-only, host-locked to api.groq.com."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from llm.base import ChatMessage, ChatResponse
from security.groq_key import load_key, mark_rejected

logger = logging.getLogger(__name__)

ALLOWED_HOST = "api.groq.com"
DEFAULT_BASE_URL = f"https://{ALLOWED_HOST}/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
QUOTA_MESSAGE = (
    "Groq's free limit is used up for now. Planning on this PC instead."
)
PLANNER_SYSTEM = (
    "You are MiniAI's planner. Write a short JSON plan only — no tools, "
    "no prose outside JSON. Schema: {\"steps\":[{\"step\":\"...\", "
    "\"tool_hint\":\"<tool name or none>\", \"done_when\":\"<condition a "
    "tool result can prove>\"}]} with at most 8 steps."
)

_last_chosen_model: str = DEFAULT_MODEL


def last_chosen_model_name() -> str:
    return _last_chosen_model


class GroqHttpError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.retry_after = retry_after


class GroqQuotaError(GroqHttpError):
    def __init__(
        self,
        message: str = QUOTA_MESSAGE,
        *,
        http_status: int | None = 429,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, http_status=http_status, retry_after=retry_after)


class GroqAuthError(GroqHttpError):
    def __init__(
        self,
        message: str = "Key rejected by Groq",
        *,
        http_status: int | None = 401,
    ) -> None:
        super().__init__(message, http_status=http_status)


class GroqConfigError(ValueError):
    """Refused base URL or missing key."""


def assert_allowed_base_url(base_url: str) -> str:
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        raise GroqConfigError("empty Groq base URL")
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = (parsed.hostname or "").lower()
    if host != ALLOWED_HOST:
        raise GroqConfigError(
            f"Groq provider refuses host {host!r}; only {ALLOWED_HOST} is allowed"
        )
    if parsed.scheme and parsed.scheme.lower() != "https":
        raise GroqConfigError("Groq provider requires https")
    return raw


def home_to_tilde(text: str, home: str | None = None) -> str:
    """Replace the user's home path with ~ (never send absolute home)."""
    raw = text or ""
    h = (home if home is not None else str(__import__("pathlib").Path.home())).rstrip(
        "\\/"
    )
    if not h:
        return raw
    out = raw
    # Case-insensitive on Windows paths.
    pattern = re.compile(re.escape(h), re.IGNORECASE)
    out = pattern.sub("~", out)
    # Also forward-slash form.
    h_fwd = h.replace("\\", "/")
    if h_fwd != h:
        pattern2 = re.compile(re.escape(h_fwd), re.IGNORECASE)
        out = pattern2.sub("~", out)
    return out


def tool_names_only(schemas: list[dict[str, Any]] | None = None) -> list[str]:
    """Names of MiniAI tools — never schemas/args/results."""
    if schemas is None:
        try:
            from tools.registry import active_tool_schemas

            schemas = active_tool_schemas()
        except Exception:
            schemas = []
    names: list[str] = []
    for item in schemas or []:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if item.get("type") == "function" else item
        if isinstance(fn, dict):
            n = fn.get("name") or item.get("name")
        else:
            n = item.get("name")
        if n:
            names.append(str(n))
    return sorted(set(names))


def build_planner_messages(
    user_request: str,
    *,
    tool_names: list[str] | None = None,
    home: str | None = None,
) -> list[ChatMessage]:
    """Planner-only payload: system + user text (~) + tool name list.

    Never includes file contents, memory, tool results, or chat history.
    """
    names = tool_names if tool_names is not None else tool_names_only()
    safe_user = home_to_tilde(user_request or "", home=home)
    tools_line = ", ".join(names) if names else "(none)"
    user_body = (
        f"User request:\n{safe_user}\n\n"
        f"Available MiniAI tool names (names only): {tools_line}\n\n"
        "Respond with the plan JSON only."
    )
    return [
        ChatMessage(role="system", content=PLANNER_SYSTEM),
        ChatMessage(role="user", content=user_body),
    ]


def assert_planner_payload_safe(payload: dict[str, Any]) -> None:
    """Raise if payload sneaks in tools or obvious file/memory blobs."""
    if payload.get("tools"):
        raise GroqConfigError("planner payload must not include tools")
    blob = json.dumps(payload, ensure_ascii=False)
    # Heuristics: memory DB dumps / long file bodies shouldn't appear.
    lowered = blob.lower()
    for needle in ("memory_save", "\"content\": \"-----", "file_contents"):
        if needle in lowered:
            raise GroqConfigError("planner payload must not include file/memory content")


class GroqProvider:
    """Thin OpenAI-compatible client used only for planning."""

    last_request_meta: dict[str, Any] = {}

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = assert_allowed_base_url(base_url or DEFAULT_BASE_URL)
        key = (api_key if api_key is not None else load_key()) or ""
        if not key.strip():
            raise GroqConfigError("No Groq API key configured")
        self._api_key = key.strip()
        self.timeout = timeout
        self._session = session or requests.Session()
        self.model = model or DEFAULT_MODEL
        global _last_chosen_model
        _last_chosen_model = self.model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _parse_retry_after(self, response: requests.Response) -> float | None:
        raw = response.headers.get("retry-after") or response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _handle_http_error(self, response: requests.Response) -> None:
        code = int(getattr(response, "status_code", 0) or 0)
        if code < 400:
            return
        retry_after = self._parse_retry_after(response)
        text = (getattr(response, "text", "") or "")[:300]
        text = re.sub(r"gsk_[0-9A-Za-z_-]{10,}", "[REDACTED_API_KEY]", text)
        if code in (401, 403):
            mark_rejected()
            raise GroqAuthError("Key rejected by Groq", http_status=code)
        if code == 429:
            try:
                from agent.groq_quota import note_retry_after

                note_retry_after(retry_after)
            except Exception:
                pass
            raise GroqQuotaError(
                QUOTA_MESSAGE, http_status=429, retry_after=retry_after
            )
        raise GroqHttpError(
            text or f"Groq HTTP {code}",
            http_status=code,
            retry_after=retry_after,
        )

    def _build_request_meta(self, payload: dict[str, Any], messages: list[ChatMessage]) -> dict[str, Any]:
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            body_chars = len(body)
        except Exception:
            body_chars = sum(len(m.content or "") for m in messages)
        meta = {
            "model": self.model,
            "message_chars": sum(len(m.content or "") for m in messages),
            "body_chars": body_chars,
            "tool_count": 0,
            "host": ALLOWED_HOST,
            "provider": "groq",
            "time": __import__("time").time(),
        }
        self.last_request_meta = meta
        return meta

    def _note_sent(self, meta: dict[str, Any]) -> None:
        try:
            from agent.cloud_routing import note_cloud_http_sent

            note_cloud_http_sent(meta)
        except Exception:
            pass
        # Optional measure log (Round 11B): path via MINIAI_GROQ_REQUEST_LOG.
        # Never writes the API key or full user text — meta counts only.
        # Call after usage tokens are attached when possible.
        try:
            import os
            from pathlib import Path

            dest = (os.environ.get("MINIAI_GROQ_REQUEST_LOG") or "").strip()
            if dest:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                with Path(dest).open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _post(self, payload: dict[str, Any], *, timeout: float) -> requests.Response:
        assert_allowed_base_url(self.base_url)
        url = f"{self.base_url}/chat/completions"
        return self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )

    def plan(
        self,
        user_request: str,
        *,
        tool_names: list[str] | None = None,
        home: str | None = None,
        timeout: float | None = None,
    ) -> ChatResponse:
        """Planner-only call: no tools, no history, no file/memory content."""
        from agent.groq_quota import (
            check_allowed,
            estimate_tokens,
            record_request,
        )

        messages = build_planner_messages(
            user_request, tool_names=tool_names, home=home
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            # Explicitly no tools.
        }
        assert_planner_payload_safe(payload)
        est = estimate_tokens(json.dumps(payload, ensure_ascii=False))
        ok, reason = check_allowed(estimated_tokens=est)
        if not ok:
            raise GroqQuotaError(f"{QUOTA_MESSAGE} ({reason})")

        meta = self._build_request_meta(payload, messages)
        # One-shot sample for audits (shortened user text; no key).
        try:
            import os
            from pathlib import Path

            sample = (os.environ.get("MINIAI_GROQ_PAYLOAD_SAMPLE") or "").strip()
            if sample and not Path(sample).is_file():
                user_msg = ""
                for m in messages:
                    if m.role == "user":
                        user_msg = (m.content or "")[:180]
                        if len(m.content or "") > 180:
                            user_msg += "…"
                        break
                safe = {
                    "model": payload.get("model"),
                    "keys": sorted(payload.keys()),
                    "n_messages": len(payload.get("messages") or []),
                    "has_tools": bool(payload.get("tools")),
                    "user_text_short": user_msg,
                    "system_head": ((messages[0].content or "")[:120] + "…")
                    if messages
                    else "",
                }
                Path(sample).parent.mkdir(parents=True, exist_ok=True)
                Path(sample).write_text(
                    json.dumps(safe, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except Exception:
            pass
        t = float(timeout if timeout is not None else self.timeout)
        resp = self._post(payload, timeout=t)
        self._handle_http_error(resp)
        resp.encoding = "utf-8"
        data = resp.json()
        usage = data.get("usage") if isinstance(data, dict) else None
        tokens = est
        if isinstance(usage, dict):
            try:
                tokens = int(
                    usage.get("total_tokens")
                    or (
                        int(usage.get("prompt_tokens") or 0)
                        + int(usage.get("completion_tokens") or 0)
                    )
                    or est
                )
            except (TypeError, ValueError):
                tokens = est
        record_request(tokens=tokens)
        meta["tokens"] = tokens
        self.last_request_meta = meta
        self._note_sent(meta)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return ChatResponse(
            content=message.get("content", "") or "",
            finish_reason=choice.get("finish_reason"),
            tool_calls=None,  # planner never accepts tools
            raw=data,
        )

    def test_key(self, *, timeout: float = 15.0) -> dict[str, Any]:
        """Lightweight connectivity check (models list). Never returns the key."""
        assert_allowed_base_url(self.base_url)
        url = f"{self.base_url}/models"
        try:
            resp = self._session.get(url, headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            return {"ok": False, "status": "Test failed", "error": type(exc).__name__}
        if resp.status_code in (401, 403):
            mark_rejected()
            return {"ok": False, "status": "Key rejected by Groq", "error": "auth"}
        if resp.status_code == 429:
            retry_after = self._parse_retry_after(resp)
            try:
                from agent.groq_quota import note_retry_after

                note_retry_after(retry_after)
            except Exception:
                pass
            return {"ok": False, "status": "Test failed", "error": "quota"}
        if resp.status_code >= 400:
            return {"ok": False, "status": "Test failed", "error": f"http_{resp.status_code}"}
        return {"ok": True, "status": "Test OK", "model": self.model}
