"""Offline tests for config.log_rotation."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.log_rotation import read_selfcheck_summary, rotate_logs

FAILURES: list[str] = []


def _fail(name: str, msg: str) -> None:
    FAILURES.append(f"{name}: {msg}")
    print(f"FAIL {name}: {msg}")


def _ok(name: str) -> None:
    print(f"PASS {name}")


def test_protect_recent_eval_and_trim_agents() -> None:
    name = "protect_and_trim"
    with tempfile.TemporaryDirectory(prefix="miniai_logs_") as tmp:
        root = Path(tmp)
        now = time.time()
        # Recent eval/review must survive
        (root / "eval_recent.json").write_text("{}", encoding="utf-8")
        (root / "review_recent.log").write_text("x", encoding="utf-8")
        # Old eval may go
        old_eval = root / "eval_old.json"
        old_eval.write_text("{}", encoding="utf-8")
        import os

        os.utime(old_eval, (now - 40 * 86400, now - 40 * 86400))
        # Agent logs: one old, one new
        old_a = root / "agent_old.log"
        new_a = root / "agent_new.log"
        old_a.write_bytes(b"a" * 1000)
        new_a.write_bytes(b"b" * 1000)
        os.utime(old_a, (now - 20 * 86400, now - 20 * 86400))
        res = rotate_logs(root)
        if not (root / "eval_recent.json").is_file():
            _fail(name, "deleted recent eval")
            return
        if not (root / "review_recent.log").is_file():
            _fail(name, "deleted recent review")
            return
        if old_eval.is_file():
            _fail(name, "kept old eval >30d")
            return
        if old_a.is_file():
            _fail(name, "kept old agent >14d")
            return
        if not new_a.is_file():
            _fail(name, "deleted new agent")
            return
        if res["removed"] < 2:
            _fail(name, f"removed={res['removed']}")
            return
        _ok(name)


def test_selfcheck_label() -> None:
    name = "selfcheck_label"
    with tempfile.TemporaryDirectory(prefix="miniai_logs_") as tmp:
        root = Path(tmp)
        (root / "selfcheck_latest.json").write_text(
            json.dumps(
                {"passed": 16, "total": 16, "failed": 0, "date": "2026-10-25"}
            ),
            encoding="utf-8",
        )
        sc = read_selfcheck_summary(root)
        if sc.get("label") != "Self-check: 16/16 · 2026-10-25":
            _fail(name, repr(sc))
            return
        (root / "selfcheck_latest.json").write_text(
            json.dumps(
                {"passed": 14, "total": 16, "failed": 2, "date": "2026-10-25"}
            ),
            encoding="utf-8",
        )
        sc2 = read_selfcheck_summary(root)
        if "2 failed" not in sc2.get("label", "") or sc2.get("level") != "danger":
            _fail(name, repr(sc2))
            return
        _ok(name)


def main() -> int:
    print("=== test_log_rotation ===")
    test_protect_recent_eval_and_trim_agents()
    test_selfcheck_label()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(" ", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
