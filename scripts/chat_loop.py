"""Minimal chat loop for testing the LLM provider end to end.
Stage 2: no tools, no memory yet — just proves the provider abstraction
works in Python instead of raw curl calls.
Usage:
    python -m scripts.chat_loop                     # interactive REPL
    python -m scripts.chat_loop "one-shot message"   # single message, exit
"""

import sys

from llm.base import ChatMessage
from llm.lemonade.provider import LemonadeProvider


def main() -> None:
    provider = LemonadeProvider()
    history: list[ChatMessage] = []
    one_shot = sys.argv[1] if len(sys.argv) > 1 else None
    if one_shot:
        history.append(ChatMessage(role="user", content=one_shot))
        response = provider.chat(history)
        print(response.content)
        return
    print("MiniAI chat loop (Stage 2). Type 'exit' to quit.\n")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue
        history.append(ChatMessage(role="user", content=user_input))
        response = provider.chat(history)
        print(f"AI: {response.content}\n")
        history.append(ChatMessage(role="assistant", content=response.content))


if __name__ == "__main__":
    main()
