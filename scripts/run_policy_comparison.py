"""Run Wikipedia (W) and Python.org (P) browsing tasks under both thinking policies.

Usage:
  python -m scripts.run_policy_comparison
  python -m scripts.run_policy_comparison --one two_pass W
Environment MINIAI_THINKING_POLICY is set per subprocess for isolation.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "logs" / "policy_comparison_results.jsonl"

TASKS = {
    "W": (
        "Open https://en.wikipedia.org in the browser, search for ATP synthase "
        "using the site's search box, and tell me the first sentence of the article."
    ),
    "P": (
        "Open https://www.python.org in the browser, go to the Downloads page by "
        "clicking through the site, and tell me which Python version it offers to download."
    ),
}

MAPPING = {
    "browser_open": "yes",
    "browser_type": "browser_type",
    "browser_click": "yes",
}


def _analyze(transcript_path: Path, task: str, final: str) -> dict:
    events = [
        json.loads(line)
        for line in transcript_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tools = [e for e in events if e.get("type") == "tool_call"]
    llms = [e for e in events if e.get("type") == "llm_call"]
    run_end = next((e for e in events if e.get("type") == "run_end"), {})
    tool_text = "\n".join(
        (e.get("result") or "") + "\n" + json.dumps(e.get("args") or {})
        for e in tools
    )
    names = [e.get("name") for e in tools]
    urls_seen = re.findall(r"https?://[^\s\"'<>]+", tool_text)

    if task == "W":
        used_type = "browser_type" in names
        article = any("ATP_synthase" in u or "Atp_synthase" in u for u in urls_seen)
        # Key claim: a distinctive phrase from the article lead, if present in answer
        claim_bits = []
        for phrase in (
            "ATP synthase is an enzyme",
            "adenosine triphosphate",
            "catalyzes the formation",
        ):
            if phrase.lower() in (final or "").lower():
                claim_bits.append(phrase)
        grounded = bool(claim_bits) and all(
            bit.lower() in tool_text.lower() for bit in claim_bits
        )
        # Also: if answer quotes something not in tools at all, not grounded
        if not claim_bits:
            grounded = False
        completed = used_type and article
        return {
            "completed": completed,
            "grounded": grounded,
            "used_browser_type": used_type,
            "article_reached": article,
            "n_llm": len(llms),
            "wall": run_end.get("wall_clock_seconds"),
            "tools": [{"name": e.get("name"), "args": e.get("args"), "outcome": e.get("outcome")} for e in tools],
            "final": final,
            "transcript": str(transcript_path),
        }

    # Task P
    downloads = any("python.org" in u and "download" in u.lower() for u in urls_seen)
    clicked = "browser_click" in names
    completed = downloads and clicked
    # Extract version-like tokens from the final answer
    versions = re.findall(r"Python\s+(\d+\.\d+(?:\.\d+)?)", final or "", flags=re.I)
    versions += re.findall(r"\b(\d+\.\d+\.\d+)\b", final or "")
    grounded = False
    key_version = versions[0] if versions else None
    if key_version and key_version in tool_text:
        grounded = True
    return {
        "completed": completed,
        "grounded": grounded,
        "downloads_reached": downloads,
        "clicked": clicked,
        "key_version": key_version,
        "n_llm": len(llms),
        "wall": run_end.get("wall_clock_seconds"),
        "tools": [{"name": e.get("name"), "args": e.get("args"), "outcome": e.get("outcome")} for e in tools],
        "final": final,
        "transcript": str(transcript_path),
    }


def run_one(policy: str, task: str, run_id: int) -> dict:
    """Run one agent_loop in a subprocess with policy env override."""
    env = os.environ.copy()
    env["MINIAI_THINKING_POLICY"] = policy
    env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    prompt = TASKS[task]
    # Worker script embedded via -c is fragile; use a small helper module path.
    cmd = [
        sys.executable,
        "-m",
        "scripts._policy_run_once",
        policy,
        task,
        str(run_id),
        prompt,
    ]
    print(f"\n===== START policy={policy} task={task} run={run_id} =====", flush=True)
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    wall_outer = round(time.perf_counter() - started, 3)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr[-2000:] if proc.stderr else "", file=sys.stderr)
    # Worker prints RESULT_JSON=...
    result = {
        "policy": policy,
        "task": task,
        "run_id": run_id,
        "exit": proc.returncode,
        "wall_outer": wall_outer,
        "stdout_tail": (proc.stdout or "")[-1500:],
    }
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT_JSON="):
            payload = json.loads(line[len("RESULT_JSON=") :])
            result.update(payload)
            break
    return result


def verify_python_org_version() -> str | None:
    """Independent fetch of python.org/downloads for the offered version."""
    import re
    import requests

    try:
        r = requests.get(
            "https://www.python.org/downloads/",
            timeout=30,
            headers={"User-Agent": "MiniAI-policy-compare/0.1"},
        )
        r.raise_for_status()
        # Common pattern: Download Python 3.x.y
        m = re.search(r"Download Python\s+(\d+\.\d+\.\d+)", r.text)
        if m:
            return m.group(1)
        m = re.search(r"python-(\d+\.\d+\.\d+)", r.text)
        return m.group(1) if m else None
    except Exception as exc:
        print(f"python.org verify failed: {exc}")
        return None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) >= 4 and sys.argv[1] == "--one":
        # Deprecated path; worker handles one run.
        print("Use scripts._policy_run_once via run_policy_comparison")
        sys.exit(2)

    schedule = (
        [("two_pass", "W", i) for i in range(1, 4)]
        + [("two_pass", "P", i) for i in range(1, 3)]
        + [("on_after_tools", "W", i) for i in range(1, 4)]
        + [("on_after_tools", "P", i) for i in range(1, 3)]
    )
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    if RESULTS.exists():
        RESULTS.unlink()

    py_ver = verify_python_org_version()
    print(f"INDEPENDENT_PYTHON_ORG_VERSION={py_ver!r}")

    rows = []
    for policy, task, run_id in schedule:
        row = run_one(policy, task, run_id)
        if task == "P" and py_ver and row.get("key_version"):
            row["version_matches_site"] = row["key_version"] == py_ver or row[
                "key_version"
            ].startswith(py_ver.rsplit(".", 1)[0])
        rows.append(row)
        with RESULTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"DONE policy={policy} task={task} run={run_id} "
            f"completed={row.get('completed')} grounded={row.get('grounded')} "
            f"wall={row.get('wall')} n_llm={row.get('n_llm')}",
            flush=True,
        )

    # Summary table
    print("\n===== SUMMARY =====")
    for policy in ("two_pass", "on_after_tools"):
        for task in ("W", "P"):
            subset = [r for r in rows if r.get("policy") == policy and r.get("task") == task]
            success = sum(1 for r in subset if r.get("completed"))
            grounded = sum(1 for r in subset if r.get("grounded"))
            walls = [r.get("wall") for r in subset if isinstance(r.get("wall"), (int, float))]
            mean_wall = round(sum(walls) / len(walls), 1) if walls else None
            print(
                f"{policy} {task}: success={success}/{len(subset)} "
                f"grounded={grounded}/{len(subset)} mean_wall={mean_wall}"
            )

    print("\n===== UNGROUNDED RUNS =====")
    for r in rows:
        if not r.get("grounded"):
            print(f"\n--- {r.get('policy')} {r.get('task')} run={r.get('run_id')} ---")
            print(f"tools={r.get('tools')}")
            print(f"final={r.get('final')!r}")


if __name__ == "__main__":
    main()
