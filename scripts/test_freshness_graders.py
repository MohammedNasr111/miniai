"""Offline tests for Stage 12b-pre3 freshness graders (mocked truth)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.fixtures import (  # noqa: E402
    grade_fresh_firefox,
    grade_fresh_go,
    grade_fresh_linux_kernel,
    grade_fresh_node_lts,
    grade_fresh_postgres,
    grade_fresh_python,
    grade_fresh_rust,
    grade_freshness_version,
)

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name} - {detail}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} - {detail}")


def test_shared_grader() -> None:
    ok, reason = grade_freshness_version("Latest is Python 3.15.", "3.15.1", parts=2)
    _check("pass_correct_line", ok is True and "claimed_unreleased=False" in reason, reason)

    ok, reason = grade_freshness_version("Latest is Python 3.14.", "3.15.1", parts=2)
    _check(
        "fail_older",
        ok is False and "claimed_unreleased=False" in reason,
        reason,
    )

    ok, reason = grade_freshness_version("Latest is Python 3.16.", "3.15.1", parts=2)
    _check(
        "fail_unreleased_newer",
        ok is False and "claimed_unreleased=True" in reason,
        reason,
    )

    ok, reason = grade_freshness_version("Version 3.150 is out.", "3.15.1", parts=2)
    _check(
        "whole_token_no_false_positive",
        ok is False and "has_truth=False" in reason,
        reason,
    )

    ok, reason = grade_freshness_version("Node 24 LTS", "24.11.0", parts=1)
    _check("major_token_pass", ok is True, reason)

    ok, reason = grade_freshness_version(
        "Node.js 20 is LTS; support lasts 30 months as of 2026.",
        "24.11.0",
        parts=1,
    )
    _check(
        "major_ignores_months_and_year",
        ok is False
        and "claimed_unreleased=False" in reason
        and "30" not in reason
        and "2026" not in reason,
        reason,
    )


def test_truth_fetch_error() -> None:
    ctx = SimpleNamespace(answers=["Python 3.15"], state={})
    with patch(
        "eval.fixtures.fetch_truth_python_stable",
        side_effect=RuntimeError("network down"),
    ):
        ok, reason = grade_fresh_python(ctx)
    _check(
        "error_on_truth_fetch",
        ok is None and reason.startswith("ERROR:"),
        reason,
    )


def test_task_graders_mocked() -> None:
    cases = [
        (grade_fresh_python, "fetch_truth_python_stable", "3.15.1", "Python 3.15", 2),
        (grade_fresh_node_lts, "fetch_truth_node_lts", "24.11.0", "Node 24", 1),
        (
            grade_fresh_linux_kernel,
            "fetch_truth_linux_kernel",
            "6.17.2",
            "kernel 6.17",
            2,
        ),
        (grade_fresh_firefox, "fetch_truth_firefox", "144.0.1", "Firefox 144", 1),
        (grade_fresh_go, "fetch_truth_go_stable", "1.27.3", "Go 1.27", 2),
        (grade_fresh_rust, "fetch_truth_rust_stable", "1.99.1", "Rust 1.99", 2),
        (grade_fresh_postgres, "fetch_truth_postgres_major", "18", "PostgreSQL 18", 1),
    ]
    for grader, fetch_name, truth, answer, _parts in cases:
        ctx = SimpleNamespace(answers=[answer], state={})
        with patch(f"eval.fixtures.{fetch_name}", return_value=truth):
            ok, reason = grader(ctx)
        _check(f"{grader.__name__}_pass", ok is True, reason)

        ctx_old = SimpleNamespace(answers=["version 1.0 only"], state={})
        with patch(f"eval.fixtures.{fetch_name}", return_value=truth):
            ok, reason = grader(ctx_old)
        _check(f"{grader.__name__}_fail_older", ok is False, reason)


def main() -> int:
    test_shared_grader()
    test_truth_fetch_error()
    test_task_graders_mocked()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
