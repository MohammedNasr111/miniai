"""Three live Wikipedia search runs (default policy) after browser_type submit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "logs" / "live_wikipedia_submit_results.jsonl"

PROMPT = (
    "Open https://en.wikipedia.org in the browser, search for ATP synthase "
    "using the site's search box, and tell me the first sentence of the article."
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    RESULTS.write_text("", encoding="utf-8")
    env = os.environ.copy()
    # Default policy only; do not set MINIAI_THINKING_POLICY.
    env.pop("MINIAI_THINKING_POLICY", None)
    rows = []
    for run_id in (1, 2, 3):
        print(f"\n===== LIVE W RUN {run_id}/3 =====", flush=True)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts._policy_run_once",
                "two_pass",
                "W",
                str(run_id),
                PROMPT,
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        wall_outer = round(time.perf_counter() - t0, 3)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        print(stdout[-4000:] if len(stdout) > 4000 else stdout, flush=True)
        if stderr:
            print("STDERR:", stderr[-2000:], flush=True)
        result = None
        for line in stdout.splitlines():
            if line.startswith("RESULT_JSON="):
                result = json.loads(line[len("RESULT_JSON=") :])
        row = {
            "run_id": run_id,
            "exit": proc.returncode,
            "wall_outer": wall_outer,
            "stdout_tail": stdout[-2500:],
        }
        if result:
            row.update(result)
        rows.append(row)
        with RESULTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"RUN {run_id}: submit={row.get('used_submit')} "
            f"article={row.get('article_reached')} "
            f"grounded={row.get('grounded')} wall={row.get('wall')}",
            flush=True,
        )

    print("\n===== LIVE W TABLE =====")
    for row in rows:
        tools = row.get("tools") or []
        order = [
            f"{t.get('name')}({json.dumps(t.get('args') or {}, ensure_ascii=False)})"
            for t in tools
        ]
        print(
            f"run={row.get('run_id')} submit={row.get('used_submit')} "
            f"article={row.get('article_reached')} "
            f"grounded={row.get('grounded')} wall={row.get('wall')} "
            f"tools={order}"
        )
        print(f"  final={row.get('final')!r}")
    print(f"RESULTS={RESULTS}")
    failed = [r for r in rows if not r.get("article_reached") or not r.get("grounded")]
    print(f"FAILED_OR_UNGROUNDED={len(failed)}")
    sys.exit(0 if all(r.get("exit") == 0 for r in rows) else 1)


if __name__ == "__main__":
    main()
