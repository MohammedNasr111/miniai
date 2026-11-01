"""Round 13 Part 4(b) — request-coverage guidance present in system_prompt."""

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


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from scripts.agent_loop import system_prompt

    text = system_prompt()
    needle = "When the request lists several things to include in a file"
    _check("coverage_rule_present", needle in text, needle)
    _check(
        "re-read_check_present",
        "re-read the request and check each item is in the file" in text,
    )
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
