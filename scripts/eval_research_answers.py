"""Answer-level eval of web_research on saved snapshots.

Offline pages. Real Lemonade synthesis. Does not search or download.
Variants A (default ranking) and C (neighbor expansion).
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from config import settings
from llm.base import ChatMessage
from llm.lemonade.provider import LemonadeProvider
from scripts.agent_loop import system_prompt
from tools.filesystem.chunking import chunk_text
from tools.web.research_tools import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_CHUNKS_PER_PAGE,
    _Page,
    _render,
    _select,
    embed,
)

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "tests" / "fixtures" / "web_snapshots"
LOG_DIR = ROOT / "logs"
VARIANTS = (
    ("A", False),
    ("C", True),
)


def _cache_embed() -> None:
    """Identical strings are embedded once. Ranking is unchanged."""
    import tools.web.research_tools as research

    real = embed
    cache: dict[tuple[str, ...], list[list[float]]] = {}

    def cached(text):
        key = (text,) if isinstance(text, str) else tuple(text)
        if key not in cache:
            cache[key] = real(text)
        return cache[key]

    research.embed = cached


def _pages(raw_pages: list[dict]) -> list[_Page]:
    pages = []
    for item in raw_pages:
        chunks = chunk_text(
            item["text"] or "",
            chunk_size=CHUNK_SIZE,
            overlap=CHUNK_OVERLAP,
        )[:MAX_CHUNKS_PER_PAGE]
        pages.append(
            _Page(
                rank=item["rank"],
                title=item.get("title"),
                final_url=item["url"],
                chunks=chunks,
            )
        )
    return pages


def _tool_result(question: str, pages: list[_Page], skipped: list[str], expand: bool) -> str:
    if expand:
        chosen = _select(question, pages, expand_neighbors=True)
    else:
        chosen = _select(question, pages)
    return _render(question, pages, chosen, skipped)


def _history(question: str, tool_result: str) -> list[ChatMessage]:
    call = {
        "id": "eval_1",
        "type": "function",
        "function": {
            "name": "web_research",
            "arguments": json.dumps({"question": question}),
        },
    }
    return [
        ChatMessage(role="system", content=system_prompt()),
        ChatMessage(role="user", content=question),
        ChatMessage(role="assistant", content="", tool_calls=[call]),
        ChatMessage(role="tool", content=tool_result, tool_call_id="eval_1"),
    ]


def _grade(answer: str, expected: str, question_number: int) -> tuple[str, bool | None]:
    passed = expected.lower() in (answer or "").lower()
    grade = "PASS" if passed else "FAIL"
    conflict = None
    if question_number == 1:
        conflict = "3.14" in (answer or "")
    return grade, conflict


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _cache_embed()
    paths = sorted(SNAP.glob("*.json"))
    if len(paths) != 8:
        print(f"Expected 8 snapshots, found {len(paths)} in {SNAP}")
        sys.exit(1)
    first = json.loads(paths[0].read_text(encoding="utf-8"))
    if "latest stable version of Python" not in first["question"]:
        print(f"Snapshot 01 is not question 1: {first['question']}")
        sys.exit(1)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"eval_research_answers_{stamp}.log"
    provider = LemonadeProvider()
    results: list[dict] = []

    def _save() -> None:
        log_path.write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        number = int(path.stem)
        question = data["question"]
        expected = data["expected"]
        pages = _pages(data["pages"])
        skipped = list(data.get("skipped") or [])
        runs = 3 if number == 1 else 1
        rendered = {
            name: _tool_result(question, pages, skipped, expand)
            for name, expand in VARIANTS
        }
        for name, _expand in VARIANTS:
            for run in range(1, runs + 1):
                print(f"CALL Q{number} {name} run {run}", flush=True)
                started = time.perf_counter()
                response = provider.chat(
                    _history(question, rendered[name]),
                    enable_thinking=True,
                    timeout=settings.LEMONADE_SYNTHESIS_TIMEOUT_SECONDS,
                )
                elapsed = time.perf_counter() - started
                answer = response.content or ""
                usage = (response.raw or {}).get("usage") or {}
                grade, conflict = _grade(answer, expected, number)
                row = {
                    "question_number": number,
                    "question": question,
                    "expected": expected,
                    "variant": name,
                    "run": run,
                    "answer": answer,
                    "wall_clock_seconds": round(elapsed, 1),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "grade": grade,
                    "conflict": conflict,
                    "finish_reason": response.finish_reason,
                }
                if response.tool_calls:
                    row["tool_calls"] = response.tool_calls
                results.append(row)
                _save()
                print(
                    f"DONE Q{number} {name} run {run} {grade} "
                    f"conflict={conflict} {elapsed:.1f}s "
                    f"prompt={usage.get('prompt_tokens')} "
                    f"completion={usage.get('completion_tokens')}",
                    flush=True,
                )
    print(f"LOG {log_path}")
    print("EVAL_DONE")


if __name__ == "__main__":
    main()
