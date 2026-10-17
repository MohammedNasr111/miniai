"""Executes tool calls the model requests and turns the results back
into chat messages the model can read on its next turn.
"""

import json
import time
from typing import Any, Optional

from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from llm.base import ChatMessage
from security.gate import PermissionDenied, mark_untrusted
from tools.registry import TOOL_FUNCTIONS, UNTRUSTED_SOURCE_TOOLS


def _log_tool(
    transcript: Optional[Transcript],
    name: str,
    args: Any,
    result: str,
    outcome: str,
    started: float,
) -> None:
    if transcript is None:
        return
    transcript.tool_call(
        name=name,
        args=args,
        result=result,
        outcome=outcome,
        wall_clock_seconds=round(time.perf_counter() - started, 3),
    )


def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    guard: Optional[CallGuard] = None,
    transcript: Optional[Transcript] = None,
) -> list[ChatMessage]:
    results = []
    for call in tool_calls:
        started = time.perf_counter()
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
                _log_tool(transcript, name, args, blocked, "blocked", started)
                results.append(
                    ChatMessage(role="tool", content=blocked, tool_call_id=call_id)
                )
                continue
        func = TOOL_FUNCTIONS.get(name)
        outcome = "error"
        if func is None:
            content = f"Error: unknown tool '{name}'"
            outcome = "error"
        else:
            try:
                result = func(**args)
                outcome = "ok"
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
                outcome = "denied"
            except EOFError:
                content = (
                    f"Denied: no interactive input available to answer the "
                    f"permission prompt for '{name}'. Nothing was changed. "
                    "Do not retry this call."
                )
                outcome = "denied"
            except Exception as exc:
                content = f"Error: {exc}"
                outcome = "error"
        if guard is not None:
            guard.record(name, args, outcome)
        if outcome == "ok" and name in UNTRUSTED_SOURCE_TOOLS:
            mark_untrusted(name)
        print(f"[TOOL RESULT] {content[:200]}")
        _log_tool(transcript, name, args, content, outcome, started)
        results.append(
            ChatMessage(role="tool", content=content, tool_call_id=call_id)
        )
    return results
