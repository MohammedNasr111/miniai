"""Stage 4 agent loop: the model can call any tool currently
registered in tools/registry.py (see TOOL_SCHEMAS for the live list).
This is a one-shot script, not the interactive REPL yet - it sends one
user message, lets the model call tools if it wants to, feeds the
results back, and prints the model's final answer.
Usage:
    python -m scripts.agent_loop "your question here"
"""

import os
import platform
import sys

from agent.executor.executor import execute_tool_calls
from config import settings
from llm.base import ChatMessage
from llm.lemonade.provider import LemonadeProvider
from tools.registry import TOOL_SCHEMAS


def _call_model(provider, history):
    has_tool_results = any(m.role == "tool" for m in history)
    if has_tool_results:
        return provider.chat(
            history,
            tools=TOOL_SCHEMAS,
            enable_thinking=True,
            timeout=settings.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS,
        )
    return provider.chat(history, tools=TOOL_SCHEMAS)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.agent_loop \"your question\"")
        return
    provider = LemonadeProvider()
    system_prompt = (
        f"You are running on {platform.system()} in the directory "
        f"{os.getcwd()}. When the user refers to \"this project\" or "
        f"\"the project root\" with no path given, use this directory. "
        f"Always use tools to answer questions about files - never guess "
        f"or answer from assumption."
    )
    history = [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=sys.argv[1]),
    ]
    response = _call_model(provider, history)
    # Allow a couple of rounds of tool calls in case the model needs
    # more than one tool to answer (e.g. list, then read).
    rounds = 0
    while response.tool_calls and rounds < 5:
        history.append(
            ChatMessage(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            )
        )
        history.extend(execute_tool_calls(response.tool_calls))
        response = _call_model(provider, history)
        rounds += 1
    if response.tool_calls:
        print(
            f"\nStopped after {rounds} tool rounds without a final answer "
            f"(round cap reached)."
        )
        return
    print(f"\nFinal answer: {response.content}")


if __name__ == "__main__":
    main()
