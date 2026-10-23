"""Offline tests: context budget never exceeds ctx - reserve; trim marker present."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_budget import (  # noqa: E402
    CONTEXT_BUDGET_TOKENS,
    enforce_context_budget,
    estimate_prompt_tokens,
)
from llm.base import ChatMessage  # noqa: E402

FAILURES = 0
MARKER = "[trimmed to fit]"


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def main() -> int:
    huge = "X" * (600 * 1024)
    system = ChatMessage(role="system", content="You are MiniAI. " + ("s" * 200))
    user = ChatMessage(role="user", content="What are the 10 biggest files?")
    tool = ChatMessage(
        role="tool",
        content=huge,
        tool_call_id="t1",
    )
    older_user = ChatMessage(role="user", content="older question " + ("o" * 5000))
    older_asst = ChatMessage(role="assistant", content="older answer " + ("a" * 5000))
    history = [system, older_user, older_asst, user, tool]

    # Fake tools schema of modest size.
    tools = [{"type": "function", "function": {"name": "list_directory"}}]
    before = estimate_prompt_tokens(history, tools)
    enforce_context_budget(history, tools=tools)
    after = estimate_prompt_tokens(history, tools=tools)

    _check(
        "under_budget",
        after <= CONTEXT_BUDGET_TOKENS,
        f"before={before:.0f} after={after:.0f} budget={CONTEXT_BUDGET_TOKENS}",
    )
    _check(
        "marker_present",
        MARKER in (history[-1].content or ""),
        f"tool_len={len(history[-1].content or '')}",
    )
    _check(
        "system_untouched",
        history[0].content.startswith("You are MiniAI."),
        history[0].content[:40],
    )
    _check(
        "latest_user_untouched",
        history[3].content == "What are the 10 biggest files?",
        history[3].content,
    )
    # Cap at 12k first means even without further shrink, tool starts trimmed.
    _check(
        "tool_capped",
        len(history[-1].content or "") <= 12_000 + 50,
        f"len={len(history[-1].content or '')}",
    )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
