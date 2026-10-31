"""Round 11 Part 3 — run targets+guards ×3 for one planner mode; write summary JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["qa_h_code_cli", "qa_h_multistep", "qa_m_organise"]
GUARDS = ["qa_h_code_debug", "qa_h_code_website", "qa_m_code_small"]
ALL = TARGETS + GUARDS


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "off").strip().lower()
    if mode not in ("off", "local", "groq"):
        print("usage: round11_measure_mode.py off|local|groq", file=sys.stderr)
        return 2
    out = ROOT / "logs" / f"round11_{mode}_targets.json"
    os.environ["MINIAI_PLANNER"] = mode
    os.environ["MINIAI_EARLY_ABORT"] = "off"
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    tasks = ",".join(ALL)
    cmd = [
        str(py),
        "-m",
        "eval.run",
        "--suite",
        "full",
        "--task",
        tasks,
        "--repeat",
        "3",
        "--force",
    ]
    print(f"[round11] mode={mode} tasks={tasks} → {out}", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=False,
        env=os.environ.copy(),
    )
    elapsed = round(time.perf_counter() - t0, 1)
    # Pick latest eval_*.json
    evals = sorted(
        (ROOT / "logs").glob("eval_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not evals:
        print("NO_EVAL_JSON", flush=True)
        return 1
    src = evals[0]
    data = json.loads(src.read_text(encoding="utf-8"))
    raw = data.get("raw_runs") or []
    # Expect 6 tasks × 3 = 18
    by_id: dict[str, list] = {}
    for t in raw:
        by_id.setdefault(t.get("id") or "", []).append(t)

    def score(ids: list[str]) -> dict:
        passes = 0
        walls = []
        rows = []
        for i in ids:
            runs = by_id.get(i) or []
            p = sum(1 for r in runs if r.get("pass"))
            passes += p
            for r in runs:
                w = r.get("wall_s")
                if w is not None:
                    walls.append(float(w))
                rows.append(
                    {
                        "id": i,
                        "pass": bool(r.get("pass")),
                        "wall_s": r.get("wall_s"),
                        "answer_head": str(r.get("answer") or r.get("shown") or "")[:400],
                    }
                )
        return {
            "passes": passes,
            "out_of": len(ids) * 3,
            "mean_wall": (sum(walls) / len(walls)) if walls else None,
            "rows": rows,
        }

    summary = {
        "mode": mode,
        "eval_path": str(src),
        "eval_exit": proc.returncode,
        "elapsed_s": elapsed,
        "n_raw": len(raw),
        "targets": score(TARGETS),
        "guards": score(GUARDS),
        "by_id": {
            k: {
                "passes": sum(1 for r in v if r.get("pass")),
                "n": len(v),
                "walls": [r.get("wall_s") for r in v],
            }
            for k, v in by_id.items()
        },
        "safety": data.get("safety"),
        "model": data.get("model"),
    }
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    # Also copy full eval beside it for the report
    dest_full = ROOT / "logs" / f"round11_{mode}_targets_eval.json"
    dest_full.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(
        f"[round11] wrote {out} targets={summary['targets']['passes']}/"
        f"{summary['targets']['out_of']} guards={summary['guards']['passes']}/"
        f"{summary['guards']['out_of']} mean_wall_t={summary['targets']['mean_wall']}",
        flush=True,
    )
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
