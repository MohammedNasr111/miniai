"""Round 8b Part 2: log redaction + run_tests result node labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from agent.log_redact import redact_text  # noqa: E402
from agent.transcript import Transcript  # noqa: E402
from app.run_result_label import run_result_node  # noqa: E402
from security.gemini_key import save_key  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


PASS_BODY = (
    "exit_code: 0\n--- stdout ---\n"
    "..\n============================== 4 passed in 0.05s ===============================\n"
)

FAIL_BODY = (
    "exit_code: 2\n--- stdout ---\n"
    "ERROR collecting tests/test_x.py\n"
    "ModuleNotFoundError: No module named 'command_line_expense_tracker'\n"
    "=========================== short test summary info ===========================\n"
    "ERROR tests/test_x.py\n"
    "!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n"
    "1 error in 0.12s\n"
)


def main() -> None:
    fake = "AIzaSyFAKE-R8B-LOG-REDACT-KEY99"
    save_key(fake)

    # Redact helper
    sample = f"Bearer {fake} and also AIzaSyOtherFakeKeyABCDEFG1234567890"
    red = redact_text(sample)
    _check("redact_stored", fake not in red and "[REDACTED_API_KEY]" in red, red)
    _check("redact_aiza_pattern", "AIzaSyOther" not in red, red)

    # Transcript write redacts
    t = Transcript()
    t.write(
        "user_turn",
        user_prompt=f"use key {fake} please",
        note="AIzaSyAnotherPatternXXXXYYYYZZZZ1234",
    )
    t.close()
    raw = t.path.read_text(encoding="utf-8")
    _check("log_no_fake_key", fake not in raw, raw[:300])
    _check("log_has_redacted", "[REDACTED_API_KEY]" in raw, raw[:300])
    print(f"LOG_PROOF_LINE={raw.strip().splitlines()[0]}")

    # Result nodes
    lab, k = run_result_node("run_tests", PASS_BODY)
    _check(
        "pass_node",
        lab.startswith("Ran tests:") and "4 passed" in lab and k == "verify",
        f"{lab!r} {k}",
    )
    lab2, k2 = run_result_node("run_tests", FAIL_BODY)
    _check(
        "fail_node",
        lab2.startswith("Ran tests:")
        and ("error" in lab2.lower() or "ModuleNotFound" in lab2 or "collection" in lab2.lower())
        and k2 == "danger",
        f"{lab2!r} {k2}",
    )
    lab3, k3 = run_result_node("run_file", "exit_code: 0\n--- stdout ---\nok\n")
    _check("run_file_ok", lab3 == "Ran file: exit 0" and k3 == "verify", f"{lab3} {k3}")

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
