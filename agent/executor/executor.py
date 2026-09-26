"""Executes tool calls the model requests and turns the results back
into chat messages the model can read on its next turn.
"""

import json
from typing import Any

from llm.base import ChatMessage
from tools.registry import TOOL_FUNCTIONS


def execute_tool_calls(tool_calls: list[dict[str, Any]]) -> list[ChatMessage]:
    results = []
    for call in tool_calls:
        name = call["function"]["name"]
        call_id = call["id"]
        raw_args = call["function"]["arguments"]
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        print(f"\n[TOOL CALL] {name}({args})")
        func = TOOL_FUNCTIONS.get(name)
        if func is None:
            content = f"Error: unknown tool '{name}'"
        else:
            try:
                result = func(**args)
                content = json.dumps(result) if not isinstance(result, str) else result
            except Exception as exc:
                content = f"Error: {exc}"
        print(f"[TOOL RESULT] {content[:200]}")
        results.append(
            ChatMessage(role="tool", content=content, tool_call_id=call_id)
        )
    return results
