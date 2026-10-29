"""Offline: Round 9 warm-up uses system+tools, max_tokens=1, supersede path."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from app.webview_approver import AppBridge
    from llm.base import ChatResponse

    bridge = AppBridge()
    bridge.push_status = lambda: None  # type: ignore[method-assign]
    bridge._model_is_loaded = lambda: True  # type: ignore[method-assign]

    captured: dict = {}

    def fake_chat(messages, tools=None, **kwargs):
        captured["messages"] = messages
        captured["tools"] = tools
        captured["kwargs"] = kwargs
        return ChatResponse(content=".", finish_reason="stop", tool_calls=None, raw={})

    fake_provider = MagicMock()
    fake_provider.chat.side_effect = fake_chat

    with patch("llm.lemonade.provider.LemonadeProvider", return_value=fake_provider), patch(
        "scripts.agent_loop.system_prompt", return_value="SYS_WARM"
    ), patch(
        "tools.registry.active_tool_schemas",
        return_value=[{"type": "function", "function": {"name": "list_directory"}}],
    ):
        bridge.start_model_warmup()
        # Join the warm thread.
        import time

        for _ in range(50):
            if not bridge._cache_warming and captured:
                break
            time.sleep(0.05)

    check("warmup_called", bool(captured), str(captured.keys()))
    msgs = captured.get("messages") or []
    check(
        "system_first",
        len(msgs) >= 2
        and getattr(msgs[0], "role", None) == "system"
        and getattr(msgs[0], "content", None) == "SYS_WARM",
        str(msgs),
    )
    check(
        "user_dot",
        len(msgs) >= 2 and getattr(msgs[1], "content", None) == ".",
        str(msgs),
    )
    kw = captured.get("kwargs") or {}
    check("max_tokens_1", kw.get("max_tokens") == 1, str(kw))
    check("thinking_off", kw.get("enable_thinking") is False, str(kw))
    check("tools_passed", bool(captured.get("tools")), str(captured.get("tools")))

    # Supersede: second warm-up generation after supersede shouldn't block ready.
    bridge2 = AppBridge()
    bridge2.push_status = lambda: None  # type: ignore[method-assign]
    bridge2._model_is_loaded = lambda: True  # type: ignore[method-assign]
    bridge2._cache_warming = True
    bridge2.supersede_warmup()
    check("supersede_clears_warming", bridge2._cache_warming is False)
    check("supersede_flag", bridge2._warmup_superseded is True)
    check("ready_stays_set", bridge2._model_ready.is_set())

    if FAILURES:
        print(f"\n{FAILURES} failure(s)")
        return 1
    print("\nAll warmup tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
