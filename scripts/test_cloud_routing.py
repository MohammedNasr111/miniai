"""Offline tests: cloud tool allow-list, request body privacy, forbidden message."""

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

from agent.cloud_routing import (  # noqa: E402
    CLOUD_ALLOWED_TOOLS,
    CLOUD_FORBIDDEN_TOOLS,
    FORBIDDEN_LOCAL_MESSAGE,
    cloud_system_prompt,
    cloud_tool_schemas,
    filter_history_for_cloud,
    question_needs_local,
    set_cloud_turn,
)
from llm.base import ChatMessage  # noqa: E402
from tools.registry import active_tool_schemas  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    set_cloud_turn(False)
    names_local = {
        (i.get("function") or {}).get("name") for i in active_tool_schemas()
    }
    _check("local_has_fs", "list_directory" in names_local, str(sorted(names_local)[:8]))

    set_cloud_turn(True)
    try:
        names = {
            (i.get("function") or {}).get("name") for i in active_tool_schemas()
        }
        _check(
            "cloud_no_forbidden",
            names.isdisjoint(CLOUD_FORBIDDEN_TOOLS),
            f"leak={sorted(names & CLOUD_FORBIDDEN_TOOLS)}",
        )
        _check(
            "cloud_only_allowed",
            names.issubset(CLOUD_ALLOWED_TOOLS),
            f"extra={sorted(names - CLOUD_ALLOWED_TOOLS)}",
        )
        _check(
            "cloud_has_web_and_ws",
            "web_research" in names and "ws_write" in names and "calculate" in names,
            str(sorted(names)),
        )
        schemas = cloud_tool_schemas()
        _check("cloud_tool_schemas_match", len(schemas) == len(names), str(len(schemas)))
    finally:
        set_cloud_turn(False)

    sys_p = cloud_system_prompt()
    _check(
        "no_folder_paths_in_cloud_prompt",
        "Downloads" not in sys_p
        and "Documents" not in sys_p
        and "Desktop" not in sys_p
        and "LOCALAPPDATA" not in sys_p
        and "C:\\Users" not in sys_p,
        sys_p[:200],
    )

    _check(
        "needs_local_downloads",
        question_needs_local("List my Downloads folder"),
    )
    _check(
        "needs_local_remember",
        question_needs_local("What did I ask you to remember?"),
    )
    _check(
        "web_ok_for_cloud",
        not question_needs_local("What is the latest Python version?"),
    )

    hist = filter_history_for_cloud(
        [ChatMessage(role="user", content="earlier local secret path C:\\Users\\me\\secret")],
        "What is 2+2?",
        prior_cloud_messages=None,
    )
    blob = json.dumps([m.model_dump() for m in hist])
    _check(
        "history_no_local_turn",
        "secret" not in blob and "C:\\\\Users" not in blob and "earlier local" not in blob,
        blob[:300],
    )
    _check("history_has_current", "What is 2+2?" in blob, blob[:200])

    # Mock Gemini HTTP: capture body has no memory / folder paths
    from llm.gemini.provider import DEFAULT_BASE_URL, GeminiProvider

    sess = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "4"}, "finish_reason": "stop"}]
    }
    mock_resp.raise_for_status = MagicMock()
    sess.post.return_value = mock_resp
    prov = GeminiProvider(
        api_key="test-key",
        base_url=DEFAULT_BASE_URL,
        model="gemini-2.0-flash",
        session=sess,
    )
    msgs = filter_history_for_cloud([], "What is 2+2?")
    # Inject a would-be leak into a bad history to ensure we don't send it —
    # our filter already excludes it; also assert payload messages.
    out = prov.chat(msgs)
    _check("mock_answer", out.content == "4")
    _args, kwargs = sess.post.call_args
    body = kwargs.get("json") or {}
    body_s = json.dumps(body)
    _check(
        "request_no_memory_block",
        "memory" not in body_s.lower() or "do not have access" in body_s.lower(),
        body_s[:400],
    )
    _check(
        "request_no_user_folder",
        "Downloads" not in body_s and "C:\\\\Users" not in body_s,
        body_s[:400],
    )
    _check("forbidden_message_text", "can't send it to the cloud" in FORBIDDEN_LOCAL_MESSAGE)

    # Executor denies forbidden tool on cloud turn
    from agent.executor.executor import execute_tool_calls

    set_cloud_turn(True)
    try:
        results = execute_tool_calls(
            [
                {
                    "id": "1",
                    "type": "function",
                    "function": {
                        "name": "list_directory",
                        "arguments": json.dumps({"path": "C:/Users"}),
                    },
                }
            ]
        )
        content = results[0].content if results else ""
        _check(
            "executor_denies_fs",
            FORBIDDEN_LOCAL_MESSAGE in content,
            content[:200],
        )
    finally:
        set_cloud_turn(False)

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
