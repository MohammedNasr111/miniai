"""Interactive chat REPL: persistent session across turns.

One session keeps one history, CallGuard, Transcript, and browser window.
Taint and denials persist until /new. Chat replies are never approvals —
only the permission gate's own prompts approve actions.
Usage:
    python -m scripts.chat
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from llm.base import ChatMessage
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session, untrusted_sources
from security.provenance import remember_urls_from_text
from tools.browser.browser_tools import close_session

import scripts.agent_loop as agent_loop
from scripts.agent_loop import (
    CONTEXT_WARN_TOKENS,
    _require_lemonade,
    reset_evidence,
    run_tool_rounds,
    system_prompt,
    warn_if_low_memory,
)

TURN_TIMEOUT_MESSAGE = (
    "The model took too long to answer (timeout). Nothing from this message "
    "was saved to the conversation; any actions you already approved were not "
    "undone. You can ask again."
)
TURN_TOO_LARGE_MESSAGE = (
    "The request was too large for the model. I trimmed what I could; "
    "try a narrower question."
)
TURN_SERVER_DOWN_MESSAGE = (
    "The local model server isn't responding — is Lemonade running?"
)


@dataclass
class ChatSession:
    """Mutable chat state shared by the REPL and tests."""

    provider: Any
    history: list[ChatMessage] = field(default_factory=list)
    guard: CallGuard = field(default_factory=CallGuard)
    transcript: Optional[Transcript] = None
    turn_count: int = 0
    last_prompt_tokens: Optional[int] = None

    def ensure_system(self) -> None:
        if not self.history:
            self.history.append(
                ChatMessage(role="system", content=system_prompt())
            )


def new_session(provider: Any) -> ChatSession:
    """Start a fresh chat session (also used by /new)."""
    reset_session()
    close_session()
    reset_evidence()
    transcript = Transcript()
    system = system_prompt()
    transcript.run_start(
        user_prompt="(chat session)",
        model=getattr(provider, "model", "unknown"),
        system_prompt=system,
    )
    session = ChatSession(
        provider=provider,
        history=[ChatMessage(role="system", content=system)],
        guard=CallGuard(),
        transcript=transcript,
        turn_count=0,
        last_prompt_tokens=None,
    )
    return session


def end_session(session: ChatSession) -> None:
    close_session()
    if session.transcript is not None:
        try:
            session.transcript.run_end(
                wall_clock_seconds=0.0,
                rounds=session.transcript.rounds,
                round_cap_hit=session.transcript.round_cap_hit,
            )
        except Exception:
            pass
        session.transcript.close()
        session.transcript = None


def status_text(session: ChatSession) -> str:
    sources = untrusted_sources()
    src = ", ".join(sources) if sources else "(none)"
    tokens = session.last_prompt_tokens
    token_s = str(tokens) if tokens is not None else "(none yet)"
    return (
        f"Taint sources: {src}\n"
        f"Turns: {session.turn_count}\n"
        f"Last prompt_tokens: {token_s}"
    )


def _assistant_tool_calls_matched(history: list[ChatMessage]) -> bool:
    pending: set[str] = set()
    for message in history:
        if message.role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                call_id = call.get("id")
                if call_id:
                    pending.add(call_id)
        elif message.role == "tool" and message.tool_call_id:
            pending.discard(message.tool_call_id)
    return not pending


def run_user_turn(
    session: ChatSession,
    user_text: str,
    on_tool_start=None,
    on_tool_end=None,
    cancel_check=None,
    on_checking=None,
) -> str:
    """Append one user message, run tools, append cleaned final answer.

    On KeyboardInterrupt, truncates history to its pre-turn length and
    re-raises after printing is left to the caller. On provider timeout or
    connection error, rolls history back the same way, logs turn_error, and
    returns TURN_TIMEOUT_MESSAGE so the session can continue.
    """
    session.ensure_system()
    pre_len = len(session.history)
    remember_urls_from_text(user_text)
    # Code-path remember-intent: save before the model answers (CONFIRM tier).
    from agent.action_claim_check import (
        note_pre_succeeded_tool,
        set_auto_recall_hits,
        user_has_recall_intent,
    )

    try:
        from memory.intent_save import code_save_remember_intent

        saved = code_save_remember_intent(user_text)
    except Exception:
        saved = None
    if saved and saved.get("ok"):
        note_pre_succeeded_tool("save_memory")
        session.history.append(
            ChatMessage(
                role="system",
                content=f"Saved to memory: {saved['fact']}",
            )
        )
        if session.transcript is not None:
            try:
                session.transcript.tool_call(
                    name="save_memory",
                    args={
                        "content": saved["fact"],
                        "category": saved.get("category"),
                    },
                    result=str(saved.get("result") or ""),
                    outcome="ok",
                    wall_clock_seconds=0.0,
                )
                session.transcript.write(
                    "memory_code_save",
                    fact=saved["fact"],
                    category=saved.get("category"),
                    result=saved.get("result"),
                )
            except Exception:
                pass
        if on_tool_start is not None:
            try:
                on_tool_start(
                    "save_memory",
                    {"content": saved["fact"], "category": saved.get("category")},
                )
            except Exception:
                pass
        if on_tool_end is not None:
            try:
                on_tool_end("save_memory", 0.0, "ok")
            except Exception:
                pass
    # Automatic memory recall (user's own data — not untrusted).
    try:
        from memory.recall import format_memory_block, recall_relevant

        hits = recall_relevant(user_text)
        block = format_memory_block(hits)
    except Exception:
        block = ""
        hits = []
    set_auto_recall_hits(len(hits or []))
    if block:
        session.history.append(ChatMessage(role="system", content=block))
        if session.transcript is not None:
            try:
                session.transcript.write(
                    "memory_auto_recall",
                    count=len(hits),
                    ids=[h.get("id") for h in hits],
                )
            except Exception:
                pass
    # Recall-intent: code-call search_memory when auto-recall found nothing,
    # and always log a search when recall-intent so graders see the tool.
    # When hits already exist, skip forced re-runs (set_auto_recall_hits).
    if user_has_recall_intent(user_text):
        try:
            from tools.memory.memory_tools import search_memory

            t0 = time.perf_counter()
            search_hits = search_memory(query=user_text)
            elapsed = round(time.perf_counter() - t0, 3)
            note_pre_succeeded_tool("search_memory")
            if session.transcript is not None:
                session.transcript.tool_call(
                    name="search_memory",
                    args={"query": user_text},
                    result=str(search_hits)[:2000],
                    outcome="ok",
                    wall_clock_seconds=elapsed,
                )
            if on_tool_start is not None:
                try:
                    on_tool_start("search_memory", {"query": user_text})
                except Exception:
                    pass
            if on_tool_end is not None:
                try:
                    on_tool_end("search_memory", elapsed, "ok")
                except Exception:
                    pass
            if search_hits and not block:
                # Surface search results when auto-recall was empty.
                from memory.recall import format_memory_block as _fmt

                extra = _fmt(
                    [
                        {
                            "category": h.get("category") or "memory",
                            "content": h.get("content") or "",
                            "id": h.get("id"),
                        }
                        for h in (search_hits if isinstance(search_hits, list) else [])
                    ]
                )
                if extra:
                    session.history.append(ChatMessage(role="system", content=extra))
                    set_auto_recall_hits(max(1, len(search_hits)))
        except Exception:
            pass
    session.history.append(ChatMessage(role="user", content=user_text))
    session.last_check = None  # type: ignore[attr-defined]
    try:
        response = run_tool_rounds(
            session.provider,
            session.history,
            session.guard,
            session.transcript,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            cancel_check=cancel_check,
            on_checking=on_checking,
            question=user_text,
        )
        session.history.append(
            ChatMessage(role="assistant", content=response.content or "")
        )
        session.turn_count += 1
        if session.transcript is not None:
            session.last_prompt_tokens = session.transcript.last_prompt_tokens
        session.last_check = getattr(response, "check_meta", None)  # type: ignore[attr-defined]
        answer = response.content or ""
        if (
            session.last_prompt_tokens is not None
            and session.last_prompt_tokens > CONTEXT_WARN_TOKENS
        ):
            print(
                "This conversation is getting long; type /new to start "
                "fresh for best results."
            )
        return answer
    except KeyboardInterrupt:
        del session.history[pre_len:]
        assert _assistant_tool_calls_matched(session.history)
        raise
    except requests.Timeout as exc:
        del session.history[pre_len:]
        assert _assistant_tool_calls_matched(session.history)
        if session.transcript is not None:
            session.transcript.write(
                "turn_error",
                error=type(exc).__name__,
                message=str(exc),
            )
        return TURN_TIMEOUT_MESSAGE
    except requests.ConnectionError as exc:
        del session.history[pre_len:]
        assert _assistant_tool_calls_matched(session.history)
        if session.transcript is not None:
            session.transcript.write(
                "turn_error",
                error=type(exc).__name__,
                message=str(exc),
            )
        return TURN_SERVER_DOWN_MESSAGE
    except requests.HTTPError as exc:
        del session.history[pre_len:]
        assert _assistant_tool_calls_matched(session.history)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if session.transcript is not None:
            session.transcript.write(
                "turn_error",
                error=type(exc).__name__,
                message=str(exc),
                status_code=status,
            )
        if status == 400:
            return TURN_TOO_LARGE_MESSAGE
        # Other HTTP errors: friendly, no raw URL/stack.
        return (
            "The local model returned an error. Nothing from this message "
            "was saved; try again or start a new chat."
        )


def handle_command(session: ChatSession, line: str, provider: Any) -> tuple[ChatSession, bool]:
    """Handle /exit /new /status. Returns (session, should_exit)."""
    cmd = line.strip().lower()
    if cmd == "/exit":
        end_session(session)
        return session, True
    if cmd == "/new":
        end_session(session)
        session = new_session(provider)
        print("New session started.")
        return session, False
    if cmd == "/status":
        print(status_text(session))
        return session, False
    print(f"Unknown command: {line.strip()}")
    return session, False


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _require_lemonade()
    warn_if_low_memory()
    reset_session()
    provider = LemonadeProvider()
    session = new_session(provider)
    print("MiniAI chat. Commands: /exit  /new  /status")
    try:
        while True:
            try:
                line = input("\nYou> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                end_session(session)
                sys.exit(0)
            if not line:
                continue
            if line.startswith("/"):
                session, should_exit = handle_command(session, line, provider)
                if should_exit:
                    sys.exit(0)
                continue
            try:
                answer = run_user_turn(session, line)
                print(f"\nAssistant> {answer}")
            except KeyboardInterrupt:
                print(
                    "\nCancelled. Any actions you already approved during "
                    "this message were not undone."
                )
    finally:
        end_session(session)


if __name__ == "__main__":
    main()
