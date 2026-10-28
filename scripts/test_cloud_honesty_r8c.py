"""Round 8c Parts 2–3: classified reasons, partial wording, Footprint, quota gate."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from agent.cloud_fallback import (  # noqa: E402
    classify_cloud_error,
    fallback_header,
    note_quota_hit,
    quota_block_message,
)
from agent.cloud_routing import (  # noqa: E402
    clear_cloud_requests,
    cloud_requests_this_turn,
    footprint_lines_for_turn,
    note_cloud_http_sent,
    set_cloud_turn,
)
from llm.base import ChatMessage, ChatResponse  # noqa: E402
from llm.gemini.provider import (  # noqa: E402
    GeminiHttpError,
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
    clear_cloud_requests()
    set_cloud_turn(False)

    # --- classify with HTTP/Google detail ---
    q = GeminiQuotaError(
        http_status=429,
        google_status="RESOURCE_EXHAUSTED",
        google_message="Quota exceeded for AIzaSySHOULD-REDACT-THIS-KEY99",
    )
    reason = classify_cloud_error(q)
    _check("classify_quota_detail", "quota" in reason and "429" in reason, reason)
    _check("classify_has_resource", "RESOURCE_EXHAUSTED" in reason, reason)
    _check("classify_redacts_key", "AIzaSySHOULD" not in reason, reason)

    busy = GeminiHttpError(
        "high demand",
        http_status=503,
        google_status="UNAVAILABLE",
        google_message="This model is currently experiencing high demand",
    )
    r2 = classify_cloud_error(busy)
    _check("classify_503", "server busy" in r2 and "503" in r2, r2)

    _check(
        "header_unused",
        "wasn't used" in fallback_header(reason, used_gemini=False),
        fallback_header(reason, used_gemini=False),
    )
    partial = fallback_header(reason, used_gemini=True)
    _check(
        "header_partial",
        "stopped partway" in partial and "wasn't used" not in partial,
        partial,
    )

    # --- Footprint ledger: two successful HTTP metas, then failure path ---
    clear_cloud_requests()
    set_cloud_turn(True)
    note_cloud_http_sent(
        {"model": "gemini-flash-lite-latest", "body_chars": 120, "message_chars": 40}
    )
    note_cloud_http_sent(
        {"model": "gemini-flash-lite-latest", "body_chars": 340, "message_chars": 90}
    )
    reqs = cloud_requests_this_turn()
    lines = footprint_lines_for_turn("Build a tiny site")
    _check("fp_two_requests", len(reqs) == 2, repr(reqs))
    _check("fp_two_lines", len(lines) == 2, repr(lines))
    _check(
        "fp_body_chars",
        "120 characters" in lines[0] and "340 characters" in lines[1],
        repr(lines),
    )

    # End-to-end partial wording BEFORE a live 429 (429 persists quota gate).
    clear_cloud_requests()
    from app.prefs import set_gemini_quota_hit_at

    set_gemini_quota_hit_at(None)
    local = MagicMock()
    local.chat.return_value = ChatResponse(content="local finished", finish_reason="stop")
    session = ChatSession(provider=local)
    calls = {"n": 0}
    save_key("AIzaSyFAKE-R8C-FOOTPRINT-KEY01")
    http_e2e = MagicMock()
    models_e2e = MagicMock()
    models_e2e.status_code = 200
    models_e2e.json.return_value = {"data": [{"id": "gemini-flash-lite-latest"}]}
    http_e2e.get.return_value = models_e2e
    http_e2e.post.return_value = MagicMock(
        status_code=200,
        json=MagicMock(
            return_value={
                "choices": [
                    {
                        "message": {"content": "x", "tool_calls": None},
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
    )
    prov_e2e = GeminiProvider(
        api_key="AIzaSyFAKE-R8C-FOOTPRINT-KEY01", session=http_e2e
    )

    def _fake_rounds(prov_arg, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            note_cloud_http_sent({"body_chars": 111, "message_chars": 20})
            note_cloud_http_sent({"body_chars": 222, "message_chars": 40})
            raise GeminiQuotaError(
                http_status=429,
                google_status="RESOURCE_EXHAUSTED",
                google_message="Quota exceeded",
            )
        return ChatResponse(content="local finished", finish_reason="stop")

    with patch("scripts.chat.run_tool_rounds", side_effect=_fake_rounds):
        with patch("llm.gemini.provider.GeminiProvider", return_value=prov_e2e):
            ans = run_user_turn(session, "Build a tiny site", cloud=True)

    lines2 = list(getattr(session, "last_cloud_footprint_lines", None) or [])
    _check("e2e_fp_two", len(lines2) == 2, repr(lines2))
    _check(
        "e2e_partial_wording",
        "stopped partway" in (ans or "")
        and (ans or "").split("\n")[0].find("wasn't used") < 0,
        (ans or "")[:220],
    )
    _check(
        "e2e_reason_quota",
        "quota" in str(getattr(session, "last_fallback_reason", "")).lower(),
        repr(getattr(session, "last_fallback_reason", None)),
    )

    # Provider records only after successful HTTP (mocked): 2 OK then 429.
    clear_cloud_requests()
    set_cloud_turn(True)
    set_gemini_quota_hit_at(None)
    http = MagicMock()
    models = MagicMock()
    models.status_code = 200
    models.json.return_value = {"data": [{"id": "gemini-flash-lite-latest"}]}
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {
        "choices": [{"message": {"content": "a", "tool_calls": None}, "finish_reason": "stop"}]
    }
    ok2 = MagicMock()
    ok2.status_code = 200
    ok2.json.return_value = {
        "choices": [{"message": {"content": "b", "tool_calls": None}, "finish_reason": "stop"}]
    }
    fail = MagicMock()
    fail.status_code = 429
    fail.json.return_value = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "Quota exceeded for AIzaSySHOULD-REDACT-THIS-KEY99",
        }
    }
    fail.text = "{}"
    posts = [ok, ok2, fail]
    http.get.return_value = models
    http.post.side_effect = lambda *a, **k: posts.pop(0)
    prov = GeminiProvider(api_key="AIzaSyFAKE-R8C-FOOTPRINT-KEY01", session=http)
    msgs = [ChatMessage(role="user", content="one")]
    prov.chat(msgs)
    prov.chat(msgs)
    raised = None
    try:
        prov.chat(msgs)
    except GeminiQuotaError as exc:
        raised = exc
    _check("provider_two_recorded", len(cloud_requests_this_turn()) == 2, str(len(cloud_requests_this_turn())))
    _check("provider_third_raises", raised is not None, repr(raised))
    _check(
        "provider_reason_detailed",
        raised is not None
        and "429" in classify_cloud_error(raised)
        and "AIzaSySHOULD" not in classify_cloud_error(raised),
        classify_cloud_error(raised) if raised else "",
    )

    # --- Quota gate: after a hit, refuse to start for an hour ---
    note_quota_hit(time.time())
    msg = quota_block_message()
    _check(
        "quota_block_msg",
        bool(msg) and "free limit was reached" in (msg or ""),
        repr(msg),
    )
    session2 = ChatSession(provider=local)
    blocked = run_user_turn(session2, "hello cloud", cloud=True)
    _check(
        "quota_blocks_turn",
        blocked == msg
        and getattr(session2, "last_answered_by", None) == "cloud-blocked-quota",
        f"ans={blocked!r} by={getattr(session2, 'last_answered_by', None)}",
    )
    _check(
        "not_silent_fallback",
        getattr(session2, "last_answered_by", None) != "local-fallback",
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
