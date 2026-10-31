"""Round 13 Part 2 — low-memory / slow-speed hint triggers (offline fakes)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def test_triggers_and_cooldown() -> None:
    from app.low_memory_hint import (
        HINT_TEXT,
        hint_payload,
        reset_hint_cooldown_for_tests,
        should_show_low_memory_hint,
    )

    reset_hint_cooldown_for_tests()
    show, why = should_show_low_memory_hint(
        free_ram_gb=2.0,
        last_tok_s=13.0,
        ref_tok_s=13.0,
        now=1000.0,
        force_cooldown_clear=True,
    )
    _check("low_ram_trigger", show and why == "low_ram", f"{show} {why}")

    # Immediate second call — cooldown
    show2, why2 = should_show_low_memory_hint(
        free_ram_gb=1.0,
        last_tok_s=5.0,
        ref_tok_s=13.0,
        now=1001.0,
    )
    _check("cooldown", not show2 and why2 == "cooldown", f"{show2} {why2}")

    reset_hint_cooldown_for_tests()
    show3, why3 = should_show_low_memory_hint(
        free_ram_gb=8.0,
        last_tok_s=8.0,
        ref_tok_s=13.311,
        now=2000.0,
        force_cooldown_clear=True,
    )
    # 8.0 < 13.311 * 0.9 = 11.98
    _check("slow_tok_trigger", show3 and why3 == "slow_tok", f"{show3} {why3}")

    reset_hint_cooldown_for_tests()
    show4, why4 = should_show_low_memory_hint(
        free_ram_gb=8.0,
        last_tok_s=12.5,
        ref_tok_s=13.311,
        now=3000.0,
        force_cooldown_clear=True,
    )
    _check("no_trigger_ok", not show4 and why4 == "ok", f"{show4} {why4}")

    reset_hint_cooldown_for_tests()
    payload = hint_payload(free_ram_gb=1.5, last_tok_s=None, ref_tok_s=None)
    _check(
        "payload_text",
        payload is not None and payload.get("text") == HINT_TEXT,
        repr(payload),
    )


def test_ui_hooks() -> None:
    html = (PROJECT_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    _check("html_hint", 'id="low-mem-hint"' in html)
    _check("js_hook", "on_low_mem_hint" in js)
    _check("css_hint", ".low-mem-hint" in css)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_triggers_and_cooldown()
    test_ui_hooks()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
