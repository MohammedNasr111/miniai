"""Round 11 Part 0 — Groq provider offline tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def test_key_dpapi() -> None:
    from security.groq_key import (
        STATUS_CONNECTED,
        STATUS_NOT_CONNECTED,
        has_key,
        key_path,
        load_key,
        remove_key,
        save_key,
        ui_status,
    )

    secret = "gsk_TEST-ROUND11-KEY-NEVER-LEAK-" + os.urandom(4).hex()
    remove_key()
    _check("start_empty", not has_key() and load_key() is None, repr(ui_status()))
    out = save_key(secret)
    _check(
        "save_ok",
        out.get("ok") is True
        and out.get("status") == STATUS_CONNECTED
        and "gsk_" not in str(out)
        and secret not in str(out),
        repr(out),
    )
    blob = key_path().read_bytes()
    _check(
        "not_plaintext_on_disk",
        secret.encode("utf-8") not in blob and b"gsk_" not in blob,
        f"blob_len={len(blob)}",
    )
    _check("decrypt_roundtrip", load_key() == secret)
    st = ui_status()
    _check(
        "ui_status_safe",
        st.get("connected") is True and secret not in str(st) and "gsk_" not in str(st),
        repr(st),
    )
    rem = remove_key()
    _check(
        "remove_ok",
        rem.get("ok") is True
        and rem.get("status") == STATUS_NOT_CONNECTED
        and not has_key(),
        repr(rem),
    )


def test_host_lock() -> None:
    from llm.groq.provider import (
        ALLOWED_HOST,
        DEFAULT_BASE_URL,
        GroqConfigError,
        GroqProvider,
        assert_allowed_base_url,
    )

    _check(
        "default_host_ok",
        assert_allowed_base_url(DEFAULT_BASE_URL).startswith("https://")
        and ALLOWED_HOST in DEFAULT_BASE_URL,
        DEFAULT_BASE_URL,
    )
    refused = False
    try:
        assert_allowed_base_url("https://evil.example/v1")
    except GroqConfigError:
        refused = True
    _check("refuse_other_host", refused)

    refused2 = False
    try:
        GroqProvider(api_key="fake", base_url="https://api.openai.com/v1", model="x")
    except GroqConfigError:
        refused2 = True
    _check("provider_init_refuse_openai_host", refused2)


def test_planner_payload_safe() -> None:
    from llm.base import ChatMessage
    from llm.groq.provider import (
        DEFAULT_BASE_URL,
        DEFAULT_MODEL,
        GroqProvider,
        assert_planner_payload_safe,
        build_planner_messages,
        home_to_tilde,
    )

    home = str(Path.home())
    msgs = build_planner_messages(
        f"Organise files in {home}\\Downloads",
        tool_names=["list_directory", "move_files"],
        home=home,
    )
    blob = " ".join(m.content or "" for m in msgs)
    _check("home_replaced_with_tilde", home not in blob and "~" in blob, blob[:200])
    _check(
        "no_history_or_memory_fields",
        "memory" not in blob.lower() or "tool names" in blob.lower(),
        blob[:200],
    )
    # Only system + user
    _check("two_messages_only", len(msgs) == 2 and msgs[0].role == "system")

    payload = {
        "model": DEFAULT_MODEL,
        "messages": [m.model_dump(exclude_none=True) for m in msgs],
    }
    try:
        assert_planner_payload_safe(payload)
        safe_ok = True
    except Exception:
        safe_ok = False
    _check("payload_safe_ok", safe_ok)

    bad = dict(payload)
    bad["tools"] = [{"type": "function", "function": {"name": "list_directory"}}]
    refused = False
    try:
        assert_planner_payload_safe(bad)
    except Exception:
        refused = True
    _check("payload_refuses_tools", refused)

    # Mocked plan POST: host lock + no tools in body
    from agent import groq_quota

    groq_quota.reset_for_tests()
    sess = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"steps":[]}'}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 40},
    }
    mock_resp.text = ""
    sess.post.return_value = mock_resp
    prov = GroqProvider(
        api_key="gsk_fake_test_key_xxxxxxxx",
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_MODEL,
        session=sess,
        timeout=5.0,
    )
    out = prov.plan("Create a folder and then move notes.txt into it")
    _check("mock_plan_content", "steps" in (out.content or ""), repr(out.content))
    args, kwargs = sess.post.call_args
    url = args[0] if args else kwargs.get("url", "")
    body = kwargs.get("json") or {}
    _check("post_only_groq_host", "api.groq.com" in url, url)
    _check("post_body_no_tools", "tools" not in body, list(body.keys()))


def test_log_redact_gsk() -> None:
    from agent.log_redact import redact_text
    from security.groq_key import remove_key, save_key

    secret = "gsk_REDACT_ME_" + os.urandom(6).hex()
    remove_key()
    save_key(secret)
    sample = f"Authorization: Bearer {secret} and also gsk_OTHERFAKEabcdefghij"
    red = redact_text(sample)
    _check("stored_key_redacted", secret not in red and "[REDACTED_API_KEY]" in red, red)
    _check("gsk_pattern_redacted", "gsk_OTHERFAKE" not in red, red)
    remove_key()


def test_quota_gate_and_429_fallback() -> None:
    from agent import groq_quota
    from llm.groq.provider import (
        DEFAULT_BASE_URL,
        DEFAULT_MODEL,
        GroqProvider,
        GroqQuotaError,
        QUOTA_MESSAGE,
    )

    groq_quota.reset_for_tests()
    ok, reason = groq_quota.check_allowed(estimated_tokens=10)
    _check("quota_allows_fresh", ok and reason == "", reason)

    # Exhaust RPM
    for _ in range(groq_quota.RPM):
        groq_quota.record_request(tokens=1)
    ok2, reason2 = groq_quota.check_allowed(estimated_tokens=1)
    _check("quota_blocks_rpm", (not ok2) and "rpm" in reason2, reason2)

    groq_quota.reset_for_tests()
    # 429 path sets retry-after and raises
    sess = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.headers = {"retry-after": "12"}
    mock_resp.text = "rate limit"
    mock_resp.json.return_value = {"error": {"message": "rate limit"}}
    sess.post.return_value = mock_resp
    prov = GroqProvider(
        api_key="gsk_fake_test_key_yyyyyyyy",
        base_url=DEFAULT_BASE_URL,
        model=DEFAULT_MODEL,
        session=sess,
        timeout=5.0,
    )
    raised = False
    try:
        prov.plan("build an app and then test it")
    except GroqQuotaError as exc:
        raised = True
        _check("quota_message", QUOTA_MESSAGE.split(".")[0] in str(exc), str(exc))
        _check("retry_after_parsed", exc.retry_after == 12.0, repr(exc.retry_after))
    _check("raises_on_429", raised)
    until = groq_quota.blocked_until()
    _check("blocked_until_set", until > 0, repr(until))
    ok3, reason3 = groq_quota.check_allowed(estimated_tokens=1)
    _check("quota_blocks_after_429", not ok3, reason3)
    groq_quota.reset_for_tests()


def test_planner_pref() -> None:
    from app.prefs import get_planner_mode, set_planner_mode

    set_planner_mode("local")
    _check("pref_local", get_planner_mode() == "local")
    set_planner_mode("groq")
    _check("pref_groq", get_planner_mode() == "groq")
    set_planner_mode("off")
    _check("pref_off", get_planner_mode() == "off")
    os.environ["MINIAI_PLANNER"] = "local"
    _check("env_overrides", get_planner_mode() == "local")
    del os.environ["MINIAI_PLANNER"]
    set_planner_mode("off")


def test_footprint_groq_line() -> None:
    from agent.cloud_routing import clear_cloud_requests, footprint_lines_for_turn, note_cloud_http_sent

    clear_cloud_requests()
    note_cloud_http_sent(
        {
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "body_chars": 321,
            "message_chars": 200,
            "host": "api.groq.com",
        }
    )
    lines = footprint_lines_for_turn("hi")
    _check(
        "footprint_says_groq",
        len(lines) == 1 and "Groq" in lines[0] and "321" in lines[0],
        repr(lines),
    )
    clear_cloud_requests()


def main() -> None:
    test_key_dpapi()
    test_host_lock()
    test_planner_payload_safe()
    test_log_redact_gsk()
    test_quota_gate_and_429_fallback()
    test_planner_pref()
    test_footprint_groq_line()
    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
