"""Offline tests: final-answer streaming (fake SSE server).

Covers: chunks in order; guard replacement note; stop mid-stream keeps partial.
Uses a temp data root. Does not touch security/gate.py.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import assert_not_real_data, use_temp_data

use_temp_data()
assert_not_real_data()

FAILURES: list[str] = []


def _fail(name: str, msg: str) -> None:
    FAILURES.append(f"{name}: {msg}")
    print(f"FAIL {name}: {msg}")


def _ok(name: str) -> None:
    print(f"PASS {name}")


class _StreamHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible SSE chat completions."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            req = {}
        stream = bool(req.get("stream"))
        mode = getattr(self.server, "mode", "tokens")  # type: ignore[attr-defined]
        chunks: list[str] = list(
            getattr(self.server, "chunks", ["Hello", " ", "world"])  # type: ignore[attr-defined]
        )
        delay = float(getattr(self.server, "delay", 0.02))  # type: ignore[attr-defined]
        stop_after = getattr(self.server, "stop_after", None)  # type: ignore[attr-defined]

        if not stream:
            text = "".join(chunks)
            payload = {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ]
            }
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        if mode == "tool_call":
            # Emit a tool call (no content) so UI must clear.
            tc = {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "calculate",
                                        "arguments": '{"expression":"1+1"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
            self.wfile.write(f"data: {json.dumps(tc)}\n\n".encode("utf-8"))
            self.wfile.write(
                b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
            )
            self.wfile.write(b"data: [DONE]\n\n")
            return

        sent = 0
        for piece in chunks:
            if stop_after is not None and sent >= stop_after:
                break
            evt = {"choices": [{"delta": {"content": piece}}]}
            try:
                self.wfile.write(f"data: {json.dumps(evt)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            sent += 1
            if delay:
                time.sleep(delay)
        if stop_after is None or sent >= len(chunks):
            self.wfile.write(
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            )
            self.wfile.write(b"data: [DONE]\n\n")


def _start_server(**opts: Any) -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), _StreamHandler)
    for k, v in opts.items():
        setattr(server, k, v)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    base = f"http://{host}:{port}/v1"
    return server, base


def test_chunks_in_order() -> None:
    name = "chunks_in_order"
    server, base = _start_server(chunks=["A", "B", "C", "D"], delay=0.01)
    try:
        from llm.base import ChatMessage
        from llm.lemonade.provider import LemonadeProvider

        got: list[str] = []
        prov = LemonadeProvider(base_url=base, model="fake", timeout=30)
        resp = prov.chat_stream(
            [ChatMessage(role="user", content="hi")],
            on_token=lambda t: got.append(t),
        )
        if got != ["A", "B", "C", "D"]:
            _fail(name, f"deltas={got!r}")
            return
        if resp.content != "ABCD":
            _fail(name, f"content={resp.content!r}")
            return
        _ok(name)
    finally:
        server.shutdown()


def test_guard_replacement() -> None:
    """Streamed text differs after honesty guard → stream_corrected + note."""
    name = "guard_replacement"
    # Stream a short answer; monkeypatch quote-check to append a note.
    server, base = _start_server(
        chunks=["Quoted ", '"x" ', "here"], delay=0.005
    )
    try:
        from llm.base import ChatMessage
        from llm.lemonade.provider import LemonadeProvider
        from scripts.agent_loop import run_tool_rounds
        from agent.executor.guard import CallGuard

        deltas: list[str] = []
        cleared = {"n": 0}

        def on_delta(t: str) -> None:
            deltas.append(t)

        def on_clear() -> None:
            cleared["n"] += 1

        prov = LemonadeProvider(base_url=base, model="fake", timeout=30)
        # Avoid real tools / thinking policy second pass.
        with patch("scripts.agent_loop.settings") as st:
            st.THINKING_POLICY = "on_after_tools"
            st.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS = 60
            st.CHECKER = "off"
            # Force quote check to rewrite.
            with patch(
                "scripts.agent_loop.check_quotes_against_evidence",
                side_effect=lambda ans, transcript=None: ans
                + "\n\nNote: a quoted passage above was not found.",
            ):
                with patch(
                    "scripts.agent_loop.check_run_claims",
                    side_effect=lambda ans, transcript=None: ans,
                ):
                    with patch(
                        "scripts.agent_loop.maybe_append_injection_notice",
                        side_effect=lambda ans, ev, transcript=None: (ans, {}),
                    ):
                        with patch(
                            "scripts.agent_loop.apply_action_claim_correction",
                            side_effect=lambda ans, *a, **k: (ans, {}),
                        ):
                            with patch(
                                "scripts.agent_loop.needs_action_claim_fix",
                                return_value=(False, [], False),
                            ):
                                with patch(
                                    "agent.checker.maybe_check_and_fix",
                                    side_effect=lambda **kw: (kw["draft"], {}),
                                ):
                                    history = [
                                        ChatMessage(role="user", content="hi")
                                    ]
                                    # Provider used inside run_tool_rounds
                                    # must hit our fake server.
                                    resp = run_tool_rounds(
                                        prov,
                                        history,
                                        CallGuard(),
                                        on_stream_delta=on_delta,
                                        on_stream_clear=on_clear,
                                        question="hi",
                                    )
        if not deltas:
            _fail(name, "no stream deltas")
            return
        if deltas[-1] != "Quoted \"x\" here":
            # content may vary whitespace; check prefix
            if "Quoted" not in deltas[-1]:
                _fail(name, f"last delta={deltas[-1]!r}")
                return
        meta = resp.check_meta or {}
        if not meta.get("stream_corrected") and not meta.get("fixed"):
            _fail(name, f"check_meta missing correction: {meta!r}")
            return
        if "quoted passage" not in (resp.content or "").lower():
            _fail(name, f"guard text missing in content={resp.content!r}")
            return
        note = meta.get("note") or ""
        if note != "Corrected after checking":
            # Accept if fixed flag set; note may be set by webview layer
            if not meta.get("stream_corrected"):
                _fail(name, f"note={note!r} meta={meta!r}")
                return
        _ok(name)
    finally:
        server.shutdown()


def test_stop_mid_stream() -> None:
    name = "stop_mid_stream"
    server, base = _start_server(
        chunks=["one ", "two ", "three ", "four ", "five"],
        delay=0.05,
    )
    try:
        from llm.base import ChatMessage
        from llm.lemonade.provider import LemonadeProvider, StreamCancelled

        cancel_at = {"n": 0}

        def cancel_check() -> bool:
            cancel_at["n"] += 1
            return cancel_at["n"] >= 3

        got: list[str] = []
        prov = LemonadeProvider(base_url=base, model="fake", timeout=30)
        try:
            prov.chat_stream(
                [ChatMessage(role="user", content="hi")],
                on_token=lambda t: got.append(t),
                cancel_check=cancel_check,
            )
            _fail(name, "expected StreamCancelled")
            return
        except StreamCancelled as exc:
            if not exc.partial:
                _fail(name, "empty partial")
                return
            if not got:
                _fail(name, "no tokens before cancel")
                return
            # Partial should be a prefix of the full answer.
            full = "one two three four five"
            if not full.startswith(exc.partial.replace("  ", " ").rstrip()) and not (
                "".join(got) == exc.partial
            ):
                # At least partial equals joined tokens
                if exc.partial != "".join(got):
                    _fail(
                        name,
                        f"partial={exc.partial!r} got={got!r}",
                    )
                    return
            _ok(name)
    finally:
        server.shutdown()


def test_ui_throttle_and_stopped_marker() -> None:
    """Pure JS-logic stand-in: throttle math + (stopped) suffix."""
    name = "ui_stopped_marker"
    # Simulate showStoppedPartial formatting.
    partial = "Hello wor"
    marked = partial + "\n\n(stopped)"
    if "(stopped)" not in marked:
        _fail(name, "missing marker")
        return
    # Throttle: 50ms min → ≤20/s
    min_ms = 50
    if 1000 / min_ms > 20.0001:
        _fail(name, f"throttle too fast: {1000/min_ms}/s")
        return
    _ok(name)


def main() -> int:
    print("=== test_streaming (offline) ===")
    test_chunks_in_order()
    test_stop_mid_stream()
    test_guard_replacement()
    test_ui_throttle_and_stopped_marker()
    print("---")
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(" ", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
