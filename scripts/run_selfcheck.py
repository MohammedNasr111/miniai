"""Run MiniAI self-check and write logs/selfcheck_latest.json + history line.

Modes:
  nightly — quiet suite (quick minus needs_display tasks); no console window
  full    — full quick suite (visible windows OK; user-started from palette)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.proc import hidden_subprocess_kwargs  # noqa: E402


def _python() -> str:
    venv = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv.is_file():
        return str(venv)
    return sys.executable


def _parse_eval(eval_path: Path | None) -> dict:
    out = {
        "passed": 0,
        "failed": 0,
        "total": 0,
        "safety": "unknown",
        "eval_json": str(eval_path) if eval_path else None,
    }
    if eval_path is None or not eval_path.is_file():
        return out
    try:
        data = json.loads(eval_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return out
    results = data.get("results") or data.get("tasks") or []
    if not isinstance(results, list):
        results = []
    out["total"] = len(results)
    out["passed"] = sum(1 for r in results if r.get("pass") is True)
    out["failed"] = sum(1 for r in results if r.get("pass") is False)
    if data.get("safety") is not None:
        out["safety"] = str(data.get("safety"))
    elif data.get("safety_headline") is not None:
        out["safety"] = str(data.get("safety_headline"))
    return out


def run_selfcheck(mode: str, model: str | None = None) -> int:
    logs = PROJECT_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    stamp = started.strftime("%Y%m%d-%H%M%S")
    out_log = logs / f"selfcheck_{stamp}.log"
    out_json = logs / "selfcheck_latest.json"
    history = logs / "selfcheck_history.log"

    model = (model or os.environ.get("MINIAI_MODEL") or "Qwen3-30B-A3B-GGUF").strip()
    suite = "nightly" if mode == "nightly" else "quick"

    # Round 13 Part 3: skip when an eval run holds a live eval.lock.
    from eval.eval_lock import eval_lock_is_live

    live, detail = eval_lock_is_live()
    if live:
        msg = "skipped — evaluation running"
        print(msg, flush=True)
        finished = datetime.now()
        payload = {
            "date": finished.strftime("%Y-%m-%d"),
            "started": started.strftime("%Y-%m-%dT%H:%M:%S"),
            "finished": finished.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "mode": mode,
            "suite": suite,
            "passed": 0,
            "failed": 0,
            "total": 0,
            "safety": "skipped",
            "exit_code": 0,
            "skipped": True,
            "skip_reason": "evaluation running",
            "skip_detail": detail,
            "eval_json": None,
            "log": str(out_log),
        }
        out_log.write_text(msg + f"\n({detail})\n", encoding="utf-8")
        out_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        with history.open("a", encoding="utf-8") as fh:
            fh.write(
                f"{finished.strftime('%Y-%m-%dT%H:%M:%S')} mode={mode} "
                f"skipped=evaluation_running detail={detail}\n"
            )
        return 0

    cmd = [
        _python(),
        "-m",
        "eval.run",
        "--suite",
        suite,
        "--model",
        model,
    ]
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "MINIAI_MODEL": model}
    kw = hidden_subprocess_kwargs(
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    proc = subprocess.run(cmd, **kw)
    body = proc.stdout or ""
    out_log.write_text(body, encoding="utf-8")

    eval_files = sorted(
        logs.glob("eval_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    eval_path = eval_files[0] if eval_files else None
    # Prefer an eval written during this run (mtime >= started - 5s slack)
    started_ts = started.timestamp() - 5
    for p in eval_files:
        if p.stat().st_mtime >= started_ts:
            eval_path = p
            break

    parsed = _parse_eval(eval_path)
    finished = datetime.now()
    payload = {
        "date": finished.strftime("%Y-%m-%d"),
        "started": started.strftime("%Y-%m-%dT%H:%M:%S"),
        "finished": finished.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "mode": mode,
        "suite": suite,
        "passed": parsed["passed"],
        "failed": parsed["failed"],
        "total": parsed["total"],
        "safety": parsed["safety"],
        "exit_code": int(proc.returncode or 0),
        "eval_json": parsed["eval_json"],
        "log": str(out_log),
    }
    out_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    line = (
        f"{finished.strftime('%Y-%m-%dT%H:%M:%S')} mode={mode} suite={suite} "
        f"passed={payload['passed']}/{payload['total']} "
        f"failed={payload['failed']} safety={payload['safety']} "
        f"exit={payload['exit_code']}"
    )
    with history.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    try:
        from config.log_rotation import rotate_logs

        rotate_logs()
    except Exception:
        pass

    print(line, flush=True)
    return int(proc.returncode or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MiniAI self-check runner")
    parser.add_argument(
        "--mode",
        choices=("nightly", "full"),
        default="nightly",
        help="nightly=quiet (no display tasks); full=quick suite with windows",
    )
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    return run_selfcheck(args.mode, model=args.model)


if __name__ == "__main__":
    raise SystemExit(main())
