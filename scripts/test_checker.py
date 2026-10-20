"""Stage 12a offline tests for the answer checker."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

FAILURES = 0
EVIDENCE_LOG = PROJECT_ROOT / "logs" / "agent_20261019-235413_11344.log"


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


class ScriptedProvider:
    """Returns canned ChatResponse contents in order."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, **kwargs):
        from llm.base import ChatResponse

        self.calls.append(
            {
                "n_messages": len(messages),
                "tools": tools,
                "enable_thinking": kwargs.get("enable_thinking"),
                "response_format": kwargs.get("response_format"),
                "user": next(
                    (
                        m.content
                        for m in reversed(messages)
                        if getattr(m, "role", None) == "user"
                    ),
                    "",
                ),
            }
        )
        text = self.replies.pop(0) if self.replies else ""
        return ChatResponse(content=text, finish_reason="stop", tool_calls=None)


class FakeTranscript:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def write(self, event_type: str, **fields: Any) -> None:
        self.events.append({"type": event_type, **fields})


def _load_real_evidence() -> list[str]:
    assert EVIDENCE_LOG.is_file(), f"missing {EVIDENCE_LOG}"
    chunks: list[str] = []
    for line in EVIDENCE_LOG.read_text(encoding="utf-8").splitlines():
        ev = json.loads(line)
        if ev.get("type") == "tool_call" and ev.get("name") == "web_research":
            chunks.append(str(ev.get("result") or ""))
    assert chunks, "no web_research evidence in log"
    return chunks


def test_a_contradicted_rewrite() -> None:
    os.environ["MINIAI_CHECKER"] = "on"
    from config import settings

    settings.CHECKER = "on"
    from agent.checker import maybe_check_and_fix

    evidence = _load_real_evidence()
    # Quote must appear word-for-word in the evidence (devguide table row).
    quote = (
        "| 3.15 | PEP 790 | bugfix | 2026-10-09 | 2031-10 | Hugo van Kemenade |"
    )  # from Status of Python versions table in evidence log
    assert any(quote in e for e in evidence), "fixture quote missing from evidence"
    check_json = json.dumps(
        {
            "verdict": "fix",
            "claims": [
                {
                    "claim": "Python 3.14 is the latest stable version",
                    "status": "contradicted",
                    "source_url": "https://devguide.python.org/versions/",
                    "quote": quote,
                }
            ],
            "notes": "devguide shows 3.15 as bugfix",
        }
    )
    rewritten = (
        "According to the Python developer's guide, **Python 3.15** is in "
        "bugfix (first release 2026-10-09). Python 3.14 is also supported "
        "but is not the newest branch. Source: https://devguide.python.org/versions/"
    )
    provider = ScriptedProvider([check_json, rewritten])
    tr = FakeTranscript()
    out, meta = maybe_check_and_fix(
        provider=provider,
        question="What is the latest stable Python version?",
        draft="Python 3.14 is latest",
        evidence=evidence,
        tools_used={"web_research"},
        transcript=tr,
    )
    ok = (
        out == rewritten
        and meta is not None
        and meta.get("verdict") == "fix"
        and meta.get("fixed") is True
        and len(provider.calls) == 2
        and provider.calls[0].get("tools") is None
        and provider.calls[0].get("enable_thinking") is True
        and any(e.get("type") == "check" for e in tr.events)
        and any(e.get("type") == "check_fix" for e in tr.events)
    )
    _check(
        "a_contradicted_rewrite",
        ok,
        f"out_match={out == rewritten} meta={meta!r} calls={len(provider.calls)} "
        f"events={[e.get('type') for e in tr.events]}",
    )


def test_b_bad_quote_no_rewrite() -> None:
    os.environ["MINIAI_CHECKER"] = "on"
    from config import settings

    settings.CHECKER = "on"
    from agent.checker import maybe_check_and_fix

    evidence = ["The sky is blue on a clear day."]
    check_json = json.dumps(
        {
            "verdict": "fix",
            "claims": [
                {
                    "claim": "The sky is green",
                    "status": "contradicted",
                    "source_url": "",
                    "quote": "this quote is not in the evidence at all",
                }
            ],
            "notes": "",
        }
    )
    # If rewrite were called, this second reply would be used — must not be.
    provider = ScriptedProvider([check_json, "SHOULD_NOT_APPEAR"])
    draft = "The sky is green."
    out, meta = maybe_check_and_fix(
        provider=provider,
        question="What colour is the sky?",
        draft=draft,
        evidence=evidence,
        tools_used={"fetch_url"},
        transcript=FakeTranscript(),
    )
    ok = (
        out == draft
        and meta is not None
        and meta.get("verdict") == "ok"
        and not meta.get("fixed")
        and len(provider.calls) == 1
        and meta["claims"][0]["status"] == "unsupported"
    )
    _check(
        "b_bad_quote_no_rewrite",
        ok,
        f"out={out!r} meta={meta!r} calls={len(provider.calls)}",
    )


def test_c_bad_json_passthrough() -> None:
    os.environ["MINIAI_CHECKER"] = "on"
    from config import settings

    settings.CHECKER = "on"
    from agent.checker import maybe_check_and_fix

    provider = ScriptedProvider(["NOT JSON {{{"])
    tr = FakeTranscript()
    draft = "Unchanged answer."
    # Capture warning log
    records: list[str] = []

    class _H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    h = _H()
    log = logging.getLogger("agent.checker")
    log.addHandler(h)
    try:
        out, meta = maybe_check_and_fix(
            provider=provider,
            question="Q?",
            draft=draft,
            evidence=["some evidence text here"],
            tools_used={"web_research"},
            transcript=tr,
        )
    finally:
        log.removeHandler(h)
    ok = (
        out == draft
        and meta is not None
        and meta.get("verdict") == "ok"
        and meta.get("parse_ok") is False
        and any("bad JSON" in m for m in records)
        and len(provider.calls) == 1
    )
    _check(
        "c_bad_json_passthrough",
        ok,
        f"out={out!r} meta={meta!r} logs={records!r}",
    )


def test_d_no_evidence_tools() -> None:
    os.environ["MINIAI_CHECKER"] = "on"
    from config import settings

    settings.CHECKER = "on"
    from agent.checker import maybe_check_and_fix

    provider = ScriptedProvider(["SHOULD_NOT_BE_CALLED"])
    draft = "Hello."
    out, meta = maybe_check_and_fix(
        provider=provider,
        question="Hi",
        draft=draft,
        evidence=[],
        tools_used={"list_directory", "search_memory"},
        transcript=FakeTranscript(),
    )
    ok = out == draft and meta is None and len(provider.calls) == 0
    _check(
        "d_no_evidence_tools",
        ok,
        f"out={out!r} meta={meta!r} calls={len(provider.calls)}",
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_a_contradicted_rewrite()
    test_b_bad_quote_no_rewrite()
    test_c_bad_json_passthrough()
    test_d_no_evidence_tools()
    # Leave default off after tests.
    os.environ["MINIAI_CHECKER"] = "off"
    from config import settings

    settings.CHECKER = "off"
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
