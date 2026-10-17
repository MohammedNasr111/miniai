"""Live Wikipedia search using answer_by_action (two_pass default)."""

from __future__ import annotations

import sys
import time

from tests.support import answer_by_action

import scripts.agent_loop as agent_loop
from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from config import settings
from llm.base import ChatMessage
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session
from tools.browser.browser_tools import close_session

PROMPT = (
    "Open https://en.wikipedia.org in the browser, search for ATP synthase "
    "using the site's search box, and tell me the first sentence of the article."
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"THINKING_POLICY={settings.THINKING_POLICY}")
    agent_loop._require_lemonade()
    reset_session()
    close_session()
    provider = LemonadeProvider()
    transcript = Transcript()
    started = time.perf_counter()
    system = agent_loop.system_prompt()
    history = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=PROMPT),
    ]
    mapping = {
        "browser_open": "yes",
        "browser_type": "browser_type",
        "browser_click": "yes",
    }
    try:
        transcript.run_start(
            user_prompt=PROMPT,
            model=provider.model,
            system_prompt=system,
        )
        with answer_by_action(mapping) as prompt_log:
            guard = CallGuard()
            response = agent_loop.run_tool_rounds(
                provider, history, guard, transcript
            )
        print("\n=== PROMPT LOG ===")
        for action, prompt, answer in prompt_log:
            print(f"Action={action!r} answer={answer!r}")
            print(f"  prompt={prompt!r}")
        print(f"\nFinal answer: {response.content}")
        wall = round(time.perf_counter() - started, 3)
        transcript.run_end(
            wall_clock_seconds=wall,
            rounds=transcript.rounds,
            round_cap_hit=transcript.round_cap_hit,
        )
        print(f"WALL={wall}")
        print(f"Transcript: {transcript.path}")
    finally:
        close_session()
        transcript.close()


if __name__ == "__main__":
    main()
