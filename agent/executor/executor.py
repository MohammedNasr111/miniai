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

_BROWSER_TOOLS = frozenset(
    {"browser_open", "browser_observe", "browser_click", "browser_type"}
)
_CLOSED_MARKER = "The browser closed unexpectedly"
_PAGE_CHANGING_TOOLS = frozenset({"browser_open", "browser_click"})
_STALE_REF_TOOLS = frozenset({"browser_click", "browser_type"})


def _format_stale_args(args: Any) -> str:
    """Format tool args for the NOT DONE skip message."""
    if not isinstance(args, dict):
        return repr(args)
    parts: list[str] = []
    for key, value in args.items():
        if isinstance(value, bool):
            parts.append(f"{key}={'true' if value else 'false'}")
        elif isinstance(value, str):
            parts.append(f"{key}={value!r}")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _stale_ref_message(name: str, args: Any) -> str:
    """Explicit skip message naming the action and what did not happen."""
    call = f"{name}({_format_stale_args(args)})"
    if name == "browser_click":
        verb = "nothing was clicked"
    else:
        verb = "nothing was typed or submitted"
    return (
        f"NOT DONE: {call} was not "
        f"run, so {verb}. The page changed earlier in this "
        f"step, so element numbers chosen before seeing it may point at the wrong "
        f"thing. The newest observation is in the previous tool result; pick the "
        f"element number from it and call {name} again."
    )


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


def _flush_browser_side_effects(
    name: str,
    content: str,
    guard: Optional[CallGuard],
    transcript: Optional[Transcript],
) -> None:
    if name not in _BROWSER_TOOLS:
        return
    from tools.browser import browser_tools as bt

    for event in bt.consume_close_events():
        if transcript is not None:
            transcript.browser_event(**event)
    restarted = bt.consume_session_restarted()
    if guard is not None and (
        _CLOSED_MARKER in content or restarted
    ):
        guard.forget(set(_BROWSER_TOOLS))


def _args_submit_true(args: Any) -> bool:
    if isinstance(args, dict):
        return args.get("submit") is True
    return False


def _marks_page_changed(name: str, args: Any) -> bool:
    if name in _PAGE_CHANGING_TOOLS:
        return True
    if name == "browser_type" and _args_submit_true(args):
        return True
    return False


def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    guard: Optional[CallGuard] = None,
    transcript: Optional[Transcript] = None,
    on_tool_start: Optional[Any] = None,
    on_tool_end: Optional[Any] = None,
    cancel_check: Optional[Any] = None,
) -> list[ChatMessage]:
    results = []
    page_changed = False
    for call in tool_calls:
        if cancel_check is not None and cancel_check():
            raise KeyboardInterrupt()
        started = time.perf_counter()
        name = call["function"]["name"]
        call_id = call["id"]
        raw_args = call["function"]["arguments"]
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = raw_args
        print(f"\n[TOOL CALL] {name}({args})")
        if on_tool_start is not None:
            try:
                on_tool_start(name, args)
            except Exception:
                pass
        def _end(outcome_name: str) -> None:
            if on_tool_end is not None:
                try:
                    on_tool_end(
                        name, time.perf_counter() - started, outcome_name
                    )
                except Exception:
                    pass

        if page_changed and name in _STALE_REF_TOOLS:
            content = _stale_ref_message(name, args)
            print(f"[TOOL RESULT] {content[:200]}")
            _log_tool(transcript, name, args, content, "skipped", started)
            _end("skipped")
            results.append(
                ChatMessage(role="tool", content=content, tool_call_id=call_id)
            )
            continue
        if guard is not None:
            blocked = guard.check(name, args)
            if blocked is not None:
                print(f"[TOOL RESULT] {blocked[:200]}")
                _log_tool(transcript, name, args, blocked, "blocked", started)
                _end("blocked")
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
                from agent.context_budget import cap_tool_result_text

                content = cap_tool_result_text(content)
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
            # After a successful workspace edit, allow run_tests/run_file again
            # with the same args (otherwise the model cannot re-test a fix).
            if outcome == "ok" and name in {
                "ws_write",
                "ws_edit",
                "create_file",
                "write_file",
            }:
                guard.forget({"run_tests", "run_file", "run_code"})
        if outcome == "ok" and name in UNTRUSTED_SOURCE_TOOLS:
            mark_untrusted(name)
        if outcome == "ok" and _marks_page_changed(name, args):
            page_changed = True
        _flush_browser_side_effects(name, content, guard, transcript)
        print(f"[TOOL RESULT] {content[:200]}")
        _log_tool(transcript, name, args, content, outcome, started)
        if on_tool_end is not None:
            try:
                on_tool_end(name, time.perf_counter() - started, outcome)
            except Exception:
                pass
        results.append(
            ChatMessage(role="tool", content=content, tool_call_id=call_id)
        )
    return results
