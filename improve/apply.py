"""Append an ACCEPTABLE playbook line after explicit typed confirmation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prompts.playbook_loader import DEFAULT_PLAYBOOK, PLAYBOOK_MAX_CHARS, load_playbook_text


def apply(run_dir: Path, candidate_id: str, *, confirm_input: str | None = None) -> int:
    results_path = run_dir / "results.json"
    if not results_path.is_file():
        print(f"Missing results.json in {run_dir}")
        return 1
    results = json.loads(results_path.read_text(encoding="utf-8"))
    candidates = results.get("candidates") or []
    match = next((c for c in candidates if c.get("name") == candidate_id), None)
    if match is None:
        print(f"No candidate {candidate_id!r} in results")
        return 1
    if match.get("verdict") != "ACCEPTABLE":
        print(
            f"Refusing: candidate {candidate_id} verdict is "
            f"{match.get('verdict')!r}, not ACCEPTABLE"
        )
        return 1

    instruction = str(match.get("instruction") or "").strip()
    if not instruction:
        print("Empty instruction")
        return 1

    stamp = results.get("stamp") or run_dir.name
    current = DEFAULT_PLAYBOOK.read_text(encoding="utf-8") if DEFAULT_PLAYBOOK.is_file() else ""
    addition = f"\n# added {date.today().isoformat()} from run {stamp}\n{instruction}\n"
    new_text = current.rstrip() + "\n" + addition
    # Size check on what would load
    trial_path = run_dir / "_apply_size_check.md"
    trial_path.write_text(new_text, encoding="utf-8")
    import os

    prev = os.environ.get("MINIAI_PLAYBOOK")
    os.environ["MINIAI_PLAYBOOK"] = str(trial_path)
    try:
        loaded = load_playbook_text()
    finally:
        if prev is None:
            os.environ.pop("MINIAI_PLAYBOOK", None)
        else:
            os.environ["MINIAI_PLAYBOOK"] = prev
        trial_path.unlink(missing_ok=True)
    if not loaded and instruction:
        print(
            f"Refusing: playbook would exceed {PLAYBOOK_MAX_CHARS} chars or fail to load"
        )
        return 1

    print("=== proposed append ===")
    print(addition)
    print("=== end ===")
    print(f"Type the candidate id ({candidate_id}) to confirm:")
    typed = confirm_input if confirm_input is not None else input().strip()
    if typed != candidate_id:
        print(f"Refusing: typed {typed!r} != {candidate_id!r}")
        return 1

    DEFAULT_PLAYBOOK.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PLAYBOOK.write_text(new_text if current else addition.lstrip("\n"), encoding="utf-8")
    print(f"Appended to {DEFAULT_PLAYBOOK}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply an ACCEPTABLE playbook candidate")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("candidate_id")
    args = parser.parse_args(argv)
    return apply(args.run_dir, args.candidate_id)


if __name__ == "__main__":
    raise SystemExit(main())
