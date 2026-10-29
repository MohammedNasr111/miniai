"""Offline tests: context budget + Round 9 cache-stable thresholds."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.context_budget import (  # noqa: E402
    CACHE_STABLE_HIGH_FRAC,
    CACHE_STABLE_LOW_FRAC,
    CONTEXT_BUDGET_TOKENS,
    enforce_context_budget,
    estimate_prompt_tokens,
)
from config import settings  # noqa: E402
from llm.base import ChatMessage  # noqa: E402
from scripts.agent_loop import CROSS_TURN_OMITTED, compress_cross_turn_history  # noqa: E402

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
    with patch.object(settings, "CACHE_STABLE", False):
        enforce_context_budget(history, tools=tools)
    after = estimate_prompt_tokens(history, tools)

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

    # --- Round 9 Part 4: below 70% → no mutation ---
    small = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="hi"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_directory", "arguments": "{}"},
                }
            ],
        ),
        ChatMessage(role="tool", content="[1,2,3]", tool_call_id="c1"),
        ChatMessage(role="user", content="thanks"),
    ]
    snap = copy.deepcopy([m.model_dump() for m in small])
    est_small = estimate_prompt_tokens(small, tools)
    _check(
        "small_below_70",
        est_small <= CONTEXT_BUDGET_TOKENS * CACHE_STABLE_HIGH_FRAC,
        f"est={est_small:.0f}",
    )
    with patch.object(settings, "CACHE_STABLE", True):
        compress_cross_turn_history(small, tools=tools)
        enforce_context_budget(small, tools=tools)
    after_dump = [m.model_dump() for m in small]
    _check("below_70_untouched", after_dump == snap, "history mutated under 70%")

    # --- Above 70%: one compression gets under 50%; system + latest user intact ---
    pad = "P" * 80_000
    asst1 = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "old1",
                "type": "function",
                "function": {"name": "list_directory", "arguments": "{}"},
            }
        ],
    )
    tool_old = ChatMessage(role="tool", content=pad, tool_call_id="old1")
    asst2 = ChatMessage(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "old2",
                "type": "function",
                "function": {"name": "search_files", "arguments": "{}"},
            }
        ],
    )
    tool_old2 = ChatMessage(role="tool", content=pad, tool_call_id="old2")
    latest = "latest user question stays"
    big = [
        ChatMessage(role="system", content="SYSTEM_PROMPT_STABLE"),
        ChatMessage(role="user", content="old q"),
        asst1,
        tool_old,
        asst2,
        tool_old2,
        ChatMessage(role="user", content=latest),
    ]
    est_big = estimate_prompt_tokens(big, tools)
    _check(
        "big_above_70",
        est_big > CONTEXT_BUDGET_TOKENS * CACHE_STABLE_HIGH_FRAC,
        f"est={est_big:.0f} high={CONTEXT_BUDGET_TOKENS * CACHE_STABLE_HIGH_FRAC:.0f}",
    )
    with patch.object(settings, "CACHE_STABLE", True):
        compress_cross_turn_history(big, tools=tools)
        enforce_context_budget(big, tools=tools)
    est_after = estimate_prompt_tokens(big, tools)
    _check(
        "one_step_under_50",
        est_after <= CONTEXT_BUDGET_TOKENS * CACHE_STABLE_LOW_FRAC,
        f"after={est_after:.0f} low={CONTEXT_BUDGET_TOKENS * CACHE_STABLE_LOW_FRAC:.0f}",
    )
    _check(
        "system_stable",
        big[0].content == "SYSTEM_PROMPT_STABLE",
        big[0].content[:40],
    )
    _check(
        "latest_user_stable",
        big[-1].content == latest,
        big[-1].content,
    )
    _check(
        "earlier_tool_omitted_or_trimmed",
        (tool_old.content == CROSS_TURN_OMITTED or len(tool_old.content or "") < 20_000)
        and (
            tool_old2.content == CROSS_TURN_OMITTED
            or len(tool_old2.content or "") < 20_000
        ),
        f"t1={len(tool_old.content or '')} t2={len(tool_old2.content or '')}",
    )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
