"""Round 13 Part 3 — eval.lock vs self-check skip (offline)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def test_lock_live_and_stale() -> None:
    from eval import eval_lock as el

    with tempfile.TemporaryDirectory(prefix="miniai_r13p3_") as td:
        lock = Path(td) / "MiniAI" / "eval.lock"
        with mock.patch.object(el, "eval_lock_path", return_value=lock), mock.patch.dict(
            os.environ, {"LOCALAPPDATA": td}, clear=False
        ):
            # Force path via patch of eval_lock_path
            p = el.acquire_eval_lock(pid=12345)
            _check("acquire_writes", p.is_file(), str(p))
            data = json.loads(p.read_text(encoding="utf-8"))
            _check("has_pid", data.get("pid") == 12345, repr(data))
            live, detail = el.eval_lock_is_live()
            _check("live", live and "live" in detail, detail)

            # Stale: backdate started
            data["started"] = time.time() - (el.STALE_AFTER_S + 10)
            p.write_text(json.dumps(data), encoding="utf-8")
            live2, detail2 = el.eval_lock_is_live()
            _check("stale_cleared", not live2 and "stale" in detail2, detail2)
            _check("stale_removed", not p.is_file(), str(p.exists()))


def test_selfcheck_skips_when_lock_live() -> None:
    from eval import eval_lock as el
    from scripts import run_selfcheck as rs

    with tempfile.TemporaryDirectory(prefix="miniai_r13p3s_") as td:
        td_path = Path(td)
        lock = td_path / "MiniAI" / "eval.lock"
        logs = td_path / "logs"
        logs.mkdir()
        with mock.patch.object(el, "eval_lock_path", return_value=lock), mock.patch.object(
            rs, "PROJECT_ROOT", td_path
        ), mock.patch.dict(os.environ, {"LOCALAPPDATA": str(td_path)}, clear=False):
            el.acquire_eval_lock(pid=99)
            # Avoid actually running eval — skip path should return before subprocess
            code = rs.run_selfcheck("nightly", model="Qwen3-30B-A3B-GGUF")
            _check("exit_0", code == 0, str(code))
            latest = logs / "selfcheck_latest.json"
            _check("wrote_latest", latest.is_file(), str(latest))
            payload = json.loads(latest.read_text(encoding="utf-8"))
            _check("skipped_flag", payload.get("skipped") is True, repr(payload))
            _check(
                "skip_reason",
                payload.get("skip_reason") == "evaluation running",
                repr(payload.get("skip_reason")),
            )


def test_summary_neutral_label() -> None:
    from config.log_rotation import read_selfcheck_summary

    with tempfile.TemporaryDirectory(prefix="miniai_r13p3u_") as td:
        logs = Path(td)
        (logs / "selfcheck_latest.json").write_text(
            json.dumps(
                {
                    "date": "2026-11-01",
                    "passed": 0,
                    "failed": 0,
                    "total": 0,
                    "skipped": True,
                    "skip_reason": "evaluation running",
                }
            ),
            encoding="utf-8",
        )
        sc = read_selfcheck_summary(logs)
        _check(
            "neutral_label",
            sc.get("label") == "Skipped (eval running)" and sc.get("level") == "neutral",
            repr(sc),
        )


def test_js_neutral_color() -> None:
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    _check("js_neutral", 'selfcheck_level === "neutral"' in js and "var(--mute)" in js)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_lock_live_and_stale()
    test_selfcheck_skips_when_lock_live()
    test_summary_neutral_label()
    test_js_neutral_color()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
