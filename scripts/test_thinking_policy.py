"""Offline tests for smart thinking second-pass gating."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.base import ChatMessage
from scripts.agent_loop import should_run_thinking_second_pass

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def main() -> int:
    # Local tools only → no second pass
    hist = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="List the files in C:\\tmp"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "1",
                    "type": "function",
                    "function": {
                        "name": "list_directory",
                        "arguments": "{}",
                    },
                }
            ],
        ),
        ChatMessage(role="tool", content="[]", tool_call_id="1"),
    ]
    _check("local_no_second", should_run_thinking_second_pass(hist) is False, "list_directory")

    # Evidence tool → second pass
    hist2 = [
        ChatMessage(role="user", content="What is the population of Malaysia?"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "2",
                    "type": "function",
                    "function": {"name": "web_research", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(role="tool", content="…", tool_call_id="2"),
    ]
    _check("evidence_second", should_run_thinking_second_pass(hist2) is True, "web_research")

    # No tools, analytical → second
    hist3 = [ChatMessage(role="user", content="Why is the sky blue? Explain.")]
    _check("analytical_second", should_run_thinking_second_pass(hist3) is True, "why")

    # No tools, trivial → no second
    hist4 = [ChatMessage(role="user", content="Hi")]
    _check("trivial_no_second", should_run_thinking_second_pass(hist4) is False, "hi")

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
