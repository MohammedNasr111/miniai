"""Offline: decline wording after user denies the only mutating tool."""

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
    from agent.decline_honesty import apply_decline_wording, only_mutating_was_denied

    check(
        "only_denied",
        only_mutating_was_denied(
            denied={"create_folder"}, succeeded={"list_directory"}
        ),
    )
    check(
        "not_when_ok",
        not only_mutating_was_denied(
            denied={"create_folder"}, succeeded={"create_folder"}
        ),
    )
    check(
        "not_when_no_deny",
        not only_mutating_was_denied(denied=set(), succeeded=set()),
    )

    bad = (
        "It seems I couldn't create the folder. "
        "Would you like to try a different approach?"
    )
    fixed, meta = apply_decline_wording(
        bad, denied={"create_folder"}, succeeded=set()
    )
    check("corrected", bool(meta and meta.get("corrected")), str(meta))
    check(
        "prefix",
        fixed.startswith("You declined, so nothing was changed."),
        fixed,
    )
    check(
        "remainder",
        "different approach" in fixed,
        fixed,
    )
    check(
        "no_failure_tone",
        "couldn't create" not in fixed.lower() and "It seems" not in fixed,
        fixed,
    )

    # Unrelated prose when nothing denied
    keep = "The folder listing has three files."
    same, meta2 = apply_decline_wording(
        keep, denied=set(), succeeded={"list_directory"}
    )
    check("untouched", same == keep and meta2 is None, str(meta2))

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
