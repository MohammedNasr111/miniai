"""Run qa_m_code_small + qa_m_pdf_question ×N in a git worktree (Round 9D Part 3)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BISECT_ROOT = Path(r"C:\Users\mohdc\miniai_bisect")
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def _run_eval(worktree: Path, repeat: int) -> dict:
    env = os.environ.copy()
    env["MINIAI_EARLY_ABORT"] = "off"
    env["PYTHONPATH"] = str(worktree)
    # Keep cwd = worktree so relative imports and logs land there.
    cmd = [
        str(VENV_PY),
        "-m",
        "eval.run",
        "--suite",
        "full",
        "--task",
        "qa_m_code_small,qa_m_pdf_question",
        "--repeat",
        str(repeat),
    ]
    # --force only exists on Round 9B+ trees; probe help first.
    help_txt = subprocess.run(
        [str(VENV_PY), "-m", "eval.run", "--help"],
        cwd=str(worktree),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "--force" in ((help_txt.stdout or "") + (help_txt.stderr or "")):
        cmd.append("--force")
    log_path = worktree / "logs" / f"_bisect_eval_{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        proc = subprocess.run(
            cmd,
            cwd=str(worktree),
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    # Pick newest eval_*.json in worktree logs
    evals = sorted(
        (worktree / "logs").glob("eval_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    summary = {
        "returncode": proc.returncode,
        "log": str(log_path),
        "eval_json": str(evals[0]) if evals else None,
        "code_small": None,
        "pdf": None,
    }
    if evals:
        data = json.loads(evals[0].read_text(encoding="utf-8"))
        raw = data.get("raw_runs") or data.get("results") or []
        cs = [r for r in raw if r.get("id") == "qa_m_code_small"]
        pdf = [r for r in raw if r.get("id") == "qa_m_pdf_question"]
        if cs:
            summary["code_small"] = {
                "n": len(cs),
                "passes": sum(1 for r in cs if r.get("pass")),
                "passes_list": [bool(r.get("pass")) for r in cs],
            }
        if pdf:
            summary["pdf"] = {
                "n": len(pdf),
                "passes": sum(1 for r in pdf if r.get("pass")),
                "passes_list": [bool(r.get("pass")) for r in pdf],
            }
    return summary


def ensure_worktree(commit: str) -> Path:
    BISECT_ROOT.mkdir(parents=True, exist_ok=True)
    short = commit[:10]
    dest = BISECT_ROOT / short
    if dest.exists():
        return dest
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(dest), commit],
        cwd=str(ROOT),
        check=True,
    )
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("commit")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    # Resolve full hash
    full = subprocess.check_output(
        ["git", "rev-parse", args.commit], cwd=str(ROOT), text=True
    ).strip()
    wt = ensure_worktree(full)
    print(f"[bisect] worktree={wt} commit={full[:12]}", flush=True)
    # Model state check from MAIN tree (shared lemonade)
    st = subprocess.run(
        [str(VENV_PY), str(ROOT / "scripts" / "check_model_state.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "VERDICT=OK" not in (st.stdout or "") and "VERDICT=OK" not in (st.stderr or ""):
        print(st.stdout)
        print(st.stderr)
        print("[bisect] model_state not OK — abort", flush=True)
        return 2
    summary = _run_eval(wt, args.repeat)
    summary["commit"] = full
    summary["worktree"] = str(wt)
    out = Path(args.out) if args.out else ROOT / "logs" / f"round9d_bisect_{full[:10]}.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"WROTE {out}", flush=True)
    cs = summary.get("code_small") or {}
    # Exit 0 if code_small all pass, 1 if any fail (for bisect scripting)
    if cs.get("n") and cs.get("passes") == cs.get("n"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
