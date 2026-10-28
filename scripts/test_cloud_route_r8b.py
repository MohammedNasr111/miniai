"""Round 8b Part 1: cloud click reaches Gemini; fallback is visible."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from agent.cloud_fallback import (  # noqa: E402
    classify_cloud_error,
    coerce_cloud_flag,
    fallback_header,
)
from agent.cloud_routing import set_cloud_turn  # noqa: E402
from llm.base import ChatMessage, ChatResponse  # noqa: E402
from llm.gemini.provider import (  # noqa: E402
    DEFAULT_BASE_URL,
    GeminiProvider,
    GeminiQuotaError,
)
from scripts.chat import ChatSession, run_user_turn  # noqa: E402
from security.gemini_key import save_key  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    set_cloud_turn(False)
    _check("coerce_true_str", coerce_cloud_flag("true") is True)
    _check("coerce_false_str", coerce_cloud_flag("false") is False)
    _check("coerce_1", coerce_cloud_flag(1) is True)

    save_key("AIzaSyFAKE-R8B-TEST-KEY-0001")

    # --- Cloud click → Gemini provider (HTTP mocked) ---
    sess_http = MagicMock()
    # models list
    models_resp = MagicMock()
    models_resp.status_code = 200
    models_resp.json.return_value = {
        "data": [{"id": "gemini-2.0-flash"}, {"id": "gemini-3.8-flash"}]
    }
    models_resp.raise_for_status = MagicMock()
    # chat completion
    chat_resp = MagicMock()
    chat_resp.status_code = 200
    chat_resp.json.return_value = {
        "choices": [
            {
                "message": {"content": "Cloud says hi", "tool_calls": None},
                "finish_reason": "stop",
            }
        ]
    }
    chat_resp.raise_for_status = MagicMock()

    def _get(*a, **k):
        return models_resp

    def _post(*a, **k):
        return chat_resp

    sess_http.get.side_effect = _get
    sess_http.post.side_effect = _post

    local = MagicMock()
    local.model = "Qwen3-30B-A3B-GGUF"
    local.chat.side_effect = AssertionError("local must not be called on cloud success")
    local.chat_stream = None

    session = ChatSession(provider=local, history=[])
    session.ensure_system()

    with patch("llm.gemini.provider.requests.Session", return_value=sess_http):
        # Force GeminiProvider to use our session via constructor patch
        real_init = GeminiProvider.__init__

        def _init(self, *a, **k):
            k.setdefault("session", sess_http)
            k.setdefault("api_key", "AIzaSyFAKE-R8B-TEST-KEY-0001")
            k.setdefault("base_url", DEFAULT_BASE_URL)
            return real_init(self, *a, **k)

        with patch.object(GeminiProvider, "__init__", _init):
            # Also stub run_tool_rounds to call provider.chat once (no tools)
            def _fake_rounds(provider, history, *a, **k):
                # Cloud path must use Gemini; local fallback uses Lemonade mock.
                if not isinstance(provider, GeminiProvider):
                    return ChatResponse(
                        content="local answer after fallback", finish_reason="stop"
                    )
                return provider.chat(
                    [m for m in history if getattr(m, "role", None) != "system"]
                    or [ChatMessage(role="user", content="hi")]
                )

            with patch("scripts.chat.run_tool_rounds", side_effect=_fake_rounds):
                ans = run_user_turn(session, "What is 2+2?", cloud=True)

    _check("cloud_answer", "Cloud says hi" in (ans or ""), repr(ans)[:120])
    _check(
        "answered_by_gemini",
        getattr(session, "last_answered_by", None) == "gemini",
        repr(getattr(session, "last_answered_by", None)),
    )
    _check(
        "footprint_set",
        bool(getattr(session, "last_cloud_footprint", None))
        and "Sent to Google Gemini" in str(session.last_cloud_footprint),
        repr(getattr(session, "last_cloud_footprint", None)),
    )
    _check("local_not_called", not local.chat.called)

    # --- Forced provider error → visible fallback ---
    local2 = MagicMock()
    local2.model = "Qwen3-30B-A3B-GGUF"

    def _local_chat(messages, tools=None, **kwargs):
        return ChatResponse(content="local answer after fallback", finish_reason="stop")

    local2.chat.side_effect = _local_chat
    local2.chat_stream = None
    session2 = ChatSession(provider=local2, history=[])
    session2.ensure_system()

    with patch(
        "llm.gemini.provider.GeminiProvider",
        side_effect=GeminiQuotaError("quota"),
    ):
        with patch("scripts.chat.run_tool_rounds", side_effect=lambda *a, **k: local2.chat([])):
            ans2 = run_user_turn(session2, "Explain gravity briefly", cloud=True)

    reason2 = str(getattr(session2, "last_fallback_reason", None) or "")
    # Provider init failed before any Gemini response → "wasn't used".
    _check(
        "fallback_prefix_in_answer",
        "Gemini wasn't used:" in (ans2 or "")
        and "quota" in (ans2 or "").lower()
        and "Answered on this PC" in (ans2 or ""),
        repr(ans2)[:200],
    )
    _check(
        "fallback_reason_quota",
        "quota" in reason2.lower(),
        repr(reason2),
    )
    _check(
        "header_matches_fallback",
        getattr(session2, "last_fallback_header", None)
        == fallback_header(reason2, used_gemini=False),
        repr(getattr(session2, "last_fallback_header", None)),
    )
    _check(
        "answered_by_fallback",
        getattr(session2, "last_answered_by", None) == "local-fallback",
        repr(getattr(session2, "last_answered_by", None)),
    )

    # classify helpers
    _check(
        "classify_timeout",
        "timeout" in classify_cloud_error(TimeoutError("timed out")).lower(),
        classify_cloud_error(TimeoutError("timed out")),
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
