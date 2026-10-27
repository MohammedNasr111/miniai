"""Offline tests for Gemini provider host lock and Flash model pick."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from llm.gemini.provider import (  # noqa: E402
    ALLOWED_HOST,
    DEFAULT_BASE_URL,
    GeminiConfigError,
    GeminiProvider,
    _pick_flash_model,
    assert_allowed_base_url,
)

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    _check(
        "default_host_ok",
        assert_allowed_base_url(DEFAULT_BASE_URL).startswith("https://"),
        DEFAULT_BASE_URL,
    )
    refused = False
    try:
        assert_allowed_base_url("https://evil.example/v1")
    except GeminiConfigError as exc:
        refused = "refuses host" in str(exc).lower() or "evil" in str(exc).lower()
    _check("refuse_other_host", refused)

    refused2 = False
    try:
        GeminiProvider(api_key="fake", base_url="https://api.openai.com/v1", model="x")
    except GeminiConfigError:
        refused2 = True
    _check("provider_init_refuse_openai_host", refused2)

    # Model pick prefers flash
    picked = _pick_flash_model(
        ["models/gemini-1.5-pro", "models/gemini-2.0-flash", "models/embed"]
    )
    _check("pick_flash", "flash" in picked.lower() and "embed" not in picked.lower(), picked)

    # Mocked chat: capture that POST goes only to ALLOWED_HOST
    sess = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {"content": "hi", "tool_calls": None},
                "finish_reason": "stop",
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    sess.post.return_value = mock_resp
    # Skip live model list
    prov = GeminiProvider(
        api_key="test-key-not-real",
        base_url=DEFAULT_BASE_URL,
        model="gemini-2.0-flash",
        session=sess,
    )
    from llm.base import ChatMessage

    out = prov.chat([ChatMessage(role="user", content="ping")])
    _check("mock_chat_content", out.content == "hi", repr(out.content))
    args, kwargs = sess.post.call_args
    url = args[0] if args else kwargs.get("url", "")
    _check(
        "post_only_gemini_host",
        ALLOWED_HOST in url and "openai.com" not in url,
        url,
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
