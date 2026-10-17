"""Interactive chat REPL: persistent session across turns.

One session keeps one history, CallGuard, Transcript, and browser window.
Taint and denials persist until /new. Chat replies are never approvals —
only the permission gate's own prompts approve actions.
Usage:
    python -m scripts.chat
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Optional

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


def run_user_turn(session: ChatSession, user_text: str) -> str:
    """Append one user message, run tools, append cleaned final answer.

    On KeyboardInterrupt, truncates history to its pre-turn length and
    re-raises after printing is left to the caller.
    """
    session.ensure_system()
    pre_len = len(session.history)
    remember_urls_from_text(user_text)
    session.history.append(ChatMessage(role="user", content=user_text))
    try:
        response = run_tool_rounds(
            session.provider,
            session.history,
            session.guard,
            session.transcript,
        )
        session.history.append(
            ChatMessage(role="assistant", content=response.content or "")
        )
        session.turn_count += 1
        if session.transcript is not None:
            session.last_prompt_tokens = session.transcript.last_prompt_tokens
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
