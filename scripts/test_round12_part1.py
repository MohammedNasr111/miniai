"""Round 12 Part 1 — one status chip + System popover (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    html = (PROJECT_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    py = (PROJECT_ROOT / "app" / "webview_approver.py").read_text(encoding="utf-8")

    _check("html_status_chip", 'id="status-chip"' in html)
    _check("html_system_pop", 'id="system-pop"' in html)
    _check("html_status_retry", 'id="status-retry"' in html)
    _check(
        "html_no_sidebar_writing_speed_row",
        "Writing speed" not in html.split('aria-label="This PC"')[1].split("</section>")[0]
        or 'id="sys-tok"' in html,
        "old Writing speed mrow must not be the rail panel",
    )
    # Old engineering rows removed from visible rail (sys-* popover may still say Writing speed)
    machine = html.split('aria-label="This PC"', 1)[1].split("</section>", 1)[0]
    _check("html_no_nightly_row_in_rail", "Nightly self-check" not in machine.split("system-pop")[0])
    _check(
        "html_footer_footprint_wording",
        "Web searches and opt-in cloud requests are listed in the Footprint." in html,
    )
    _check(
        "html_no_cloud_connected_chip",
        "Cloud: connected" not in html and "Cloud: not connected" not in html,
    )

    for token in (
        ".status-chip",
        ".system-pop",
        ".status-retry",
        '[data-state="offline"]',
    ):
        _check(f"css:{token}", token in css)

    for label in (
        "Ready · on this PC",
        "Warming up…",
        "Working…",
        "Running slowly — Reload",
        "Offline — Lemonade not running",
    ):
        _check(f"js_label:{label}", label in js)

    _check("js_statusChipState", "function statusChipState" in js)
    _check("js_applyStatusChip", "function applyStatusChip" in js)
    _check("js_fillSystemPop", "function fillSystemPop" in js)
    _check("js_openSystemPop", "function openSystemPop" in js)

    _check("py_lemonade_up", '"lemonade_up"' in py or "'lemonade_up'" in py)
    _check("py_turn_busy", '"turn_busy"' in py or "'turn_busy'" in py)
    _check("py_groq_payload", "_groq_status_payload" in py)
    _check("py_gemini_not_cloud_brain", "Gemini connected" in py or "Gemini not connected" in py)
    _check("py_no_cloud_colon_connected", '"Cloud: connected"' not in py)

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
