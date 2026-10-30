"""Round 9E Part 1 — UTF-8 stream/chat decoding (no charset → not ISO-8859-1)."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0

# Characters that mojibake under ISO-8859-1 mis-decode of UTF-8 bytes.
SAMPLE = "5400–15,000 RPM; drive’s café \U0001F4BE"


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" — {detail}" if detail else ""))


class _Handler(BaseHTTPRequestHandler):
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
        text = getattr(self.server, "sample", SAMPLE)  # type: ignore[attr-defined]
        stream = bool(req.get("stream"))
        # Intentionally omit charset — reproduces the requests ISO-8859-1 fallback.
        if not stream:
            payload = {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ]
            }
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        # Split into pieces so deltas also stay intact.
        pieces = [text[:6], text[6:18], text[18:]]
        for piece in pieces:
            evt = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(
                f"data: {json.dumps(evt, ensure_ascii=False)}\n\n".encode("utf-8")
            )
            self.wfile.flush()
        self.wfile.write(
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        )
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _start() -> tuple[HTTPServer, str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.sample = SAMPLE  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def test_lemonade_stream_utf8() -> None:
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider

    server, base = _start()
    try:
        got: list[str] = []
        prov = LemonadeProvider(base_url=base, model="fake", timeout=30)
        resp = prov.chat_stream(
            [ChatMessage(role="user", content="hi")],
            on_token=lambda t: got.append(t),
        )
        joined = "".join(got)
        _check("stream_deltas_intact", joined == SAMPLE, repr(joined))
        _check("stream_content_intact", resp.content == SAMPLE, repr(resp.content))
        _check("stream_has_en_dash", "–" in resp.content)
        _check("stream_has_apostrophe", "’" in resp.content)
        _check("stream_has_eacute", "é" in resp.content)
        _check("stream_has_emoji", "\U0001F4BE" in resp.content)
        _check("stream_no_mojibake", "â€" not in resp.content and "Ã©" not in resp.content)
    finally:
        server.shutdown()


def test_lemonade_chat_utf8() -> None:
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider

    server, base = _start()
    try:
        prov = LemonadeProvider(base_url=base, model="fake", timeout=30)
        resp = prov.chat([ChatMessage(role="user", content="hi")])
        _check("chat_content_intact", resp.content == SAMPLE, repr(resp.content))
        _check("chat_no_mojibake", "â€" not in resp.content)
    finally:
        server.shutdown()


def main() -> int:
    test_lemonade_stream_utf8()
    test_lemonade_chat_utf8()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
