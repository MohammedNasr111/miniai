"""Executes tool calls the model requests and turns the results back
into chat messages the model can read on its next turn.
"""

import json
from typing import Any, Optional

from agent.executor.guard import CallGuard
from llm.base import ChatMessage
from security.gate import PermissionDenied, mark_untrusted
from tools.registry import TOOL_FUNCTIONS, UNTRUSTED_SOURCE_TOOLS


def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    guard: Optional[CallGuard] = None,
) -> list[ChatMessage]:
    results = []
    for call in tool_calls:
        name = call["function"]["name"]
        call_id = call["id"]
        raw_args = call["function"]["arguments"]
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = raw_args
        print(f"\n[TOOL CALL] {name}({args})")
        if guard is not None:
            blocked = guard.check(name, args)
            if blocked is not None:
                print(f"[TOOL RESULT] {blocked[:200]}")
                results.append(
                    ChatMessage(role="tool", content=blocked, tool_call_id=call_id)
                )
                continue
        func = TOOL_FUNCTIONS.get(name)
        succeeded = False
        if func is None:
            content = f"Error: unknown tool '{name}'"
        else:
            try:
                result = func(**args)
                succeeded = True
                if result is None:
                    content = f"OK: {name} completed successfully."
                elif isinstance(result, str):
                    content = result
                else:
                    content = json.dumps(result)
            except PermissionDenied as exc:
                message = str(exc)
                if not message.endswith("."):
                    message += "."
                content = f"Denied by user: {message} Do not retry this call."
            except EOFError:
                content = (
                    f"Denied: no interactive input available to answer the "
                    f"permission prompt for '{name}'. Nothing was changed. "
                    "Do not retry this call."
                )
            except Exception as exc:
                content = f"Error: {exc}"
        if guard is not None:
            guard.record(name, args, succeeded)
        if succeeded and name in UNTRUSTED_SOURCE_TOOLS:
            mark_untrusted(name)
        print(f"[TOOL RESULT] {content[:200]}")
        results.append(
            ChatMessage(role="tool", content=content, tool_call_id=call_id)
        )
    return results
