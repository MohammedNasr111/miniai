"""Offline: streaming markdown helpers, footprint web pages, research progress."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from app.footprint import empty_footprint, record_tool

    doc = {"footprint": empty_footprint()}
    record_tool(
        doc,
        "web_research",
        {"question": "latest Python", "pages_read": 3},
        ok=True,
    )
    fp = doc["footprint"]
    check("fp_left_search", any("Search:" in (e.get("label") or "") for e in fp["left"]))
    check(
        "fp_read_web_pages",
        any("3 web pages (untrusted)" in (e.get("label") or "") for e in fp["read"]),
        str(fp["read"]),
    )

    js = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    check("stream_uses_renderMarkdown", "renderMarkdown(text" in js and "stream-md" in js)
    check("on_chat_title", "on_chat_title" in js)
    check("header_from_history", "chatTitle.textContent = hit.title" in js)

    wa = (ROOT / "app" / "webview_approver.py").read_text(encoding="utf-8")
    check("research_progress_wired", "_on_research_progress" in wa and "set_research_progress" in wa)
    check("guard_verify_steps", "_append_guard_verify_steps" in wa)

    rt = (ROOT / "tools" / "web" / "research_tools.py").read_text(encoding="utf-8")
    check("emit_searched", 'emit_research_progress("searched"' in rt)
    check("emit_pages", '"pages_read"' in rt and "emit_research_progress" in rt)

    # Progress callback unit
    from tools.web.research_progress import emit_research_progress, set_research_progress

    seen = []
    set_research_progress(lambda k, p: seen.append((k, p)))
    emit_research_progress("searched", query="q", hit_count=2)
    emit_research_progress("pages_read", count=4)
    set_research_progress(None)
    check("progress_cb", seen == [("searched", {"query": "q", "hit_count": 2}), ("pages_read", {"count": 4})])

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
