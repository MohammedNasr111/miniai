"""Trial playbook candidates against dev, held-out, and safety evals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prompts.playbook_loader import DEFAULT_PLAYBOOK, PLAYBOOK_MAX_CHARS

EXPECTED_MODEL = "Qwen3-30B-A3B-GGUF"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes() if path.is_file() else b"")
    return h.hexdigest()


def _read_playbook_body(path: Path) -> str:
    from prompts.playbook_loader import _strip_comment_only_lines

    if not path.is_file():
        return ""
    return _strip_comment_only_lines(path.read_text(encoding="utf-8"))


def _write_temp_playbook(base_body: str, extra_line: str | None, dest: Path) -> None:
    from prompts.playbook_loader import _strip_comment_only_lines

    lines = [
        "# MiniAI playbook — trial temp (do not commit)",
        "",
    ]
    if base_body.strip():
        lines.append(base_body.strip())
        lines.append("")
    if extra_line and extra_line.strip():
        lines.append(extra_line.strip())
        lines.append("")
    text = "\n".join(lines)
    loaded = _strip_comment_only_lines(text)
    if len(loaded) > PLAYBOOK_MAX_CHARS:
        raise RuntimeError(
            f"trial playbook would be {len(loaded)} chars > {PLAYBOOK_MAX_CHARS}"
        )
    dest.write_text(text, encoding="utf-8")


def _run_eval(
    *,
    abilities: str,
    repeat: int,
    model: str,
    playbook: Path | None,
    label: str,
) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["MINIAI_CHECKER"] = "off"
    env["MINIAI_MODEL"] = model
    if playbook is not None:
        env["MINIAI_PLAYBOOK"] = str(playbook)
    else:
        env.pop("MINIAI_PLAYBOOK", None)
    cmd = [
        sys.executable,
        "-m",
        "eval.run",
        "--suite",
        "full",
        "--model",
        model,
        "--ability",
        abilities,
        "--repeat",
        str(repeat),
    ]
    print(f"[trial] {label}: {' '.join(cmd)} playbook={playbook}")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # Parse JSON path from stdout
    json_path = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("JSON:"):
            json_path = Path(line.split("JSON:", 1)[1].strip())
    if json_path is None or not json_path.is_file():
        raise RuntimeError(
            f"eval failed for {label} (exit={proc.returncode}). "
            f"stderr tail:\n{(proc.stderr or '')[-1500:]}\n"
            f"stdout tail:\n{(proc.stdout or '')[-1500:]}"
        )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {
        "json_path": str(json_path),
        "data": data,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
    }


def _summarize(eval_blob: dict[str, Any], *, safety: bool = False) -> dict[str, Any]:
    data = eval_blob["data"]
    results = data.get("results") or []
    raw = data.get("raw_runs") or results
    # Pass rate: fraction of summary results with pass True (ERROR excluded from denom).
    scored = [r for r in results if r.get("pass") is not None]
    passed = sum(1 for r in scored if r.get("pass") is True)
    total = len(scored)
    rate = (passed / total) if total else 0.0
    walls = [float(r.get("wall_s") or 0.0) for r in raw]
    mean_wall = sum(walls) / len(walls) if walls else 0.0
    models = set()
    # Verify model from top-level and agent would be same; use JSON model.
    models.add(str(data.get("model") or ""))
    safety_headline = data.get("safety")
    if safety:
        safety_ok = safety_headline == "PASS"
    else:
        safety_ok = None
    return {
        "pass_rate": round(rate, 4),
        "passed": passed,
        "total": total,
        "mean_wall_s": round(mean_wall, 3),
        "model": data.get("model"),
        "models": sorted(models),
        "safety": safety_headline,
        "safety_ok": safety_ok,
        "json_path": eval_blob["json_path"],
    }


def verdict_for(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[str, list[str]]:
    """ACCEPTABLE only if all rules pass; else REJECTED with reasons."""
    reasons: list[str] = []
    if candidate["dev"]["pass_rate"] <= current["dev"]["pass_rate"]:
        reasons.append(
            f"dev pass rate {candidate['dev']['pass_rate']} "
            f"<= current {current['dev']['pass_rate']}"
        )
    if candidate["heldout"]["pass_rate"] < current["heldout"]["pass_rate"]:
        reasons.append(
            f"held-out pass rate {candidate['heldout']['pass_rate']} "
            f"< current {current['heldout']['pass_rate']}"
        )
    if candidate["safety"]["safety"] != "PASS":
        reasons.append(f"safety not 100% (got {candidate['safety']['safety']})")
    # Mean wall across the three suites
    cur_wall = (
        current["dev"]["mean_wall_s"]
        + current["heldout"]["mean_wall_s"]
        + current["safety"]["mean_wall_s"]
    ) / 3.0
    cand_wall = (
        candidate["dev"]["mean_wall_s"]
        + candidate["heldout"]["mean_wall_s"]
        + candidate["safety"]["mean_wall_s"]
    ) / 3.0
    if cand_wall > cur_wall * 1.2 + 1e-9:
        reasons.append(
            f"mean wall {cand_wall:.3f} > current×1.2 ({cur_wall * 1.2:.3f})"
        )
    if reasons:
        return "REJECTED", reasons
    return "ACCEPTABLE", []


def run_variant(
    *,
    name: str,
    playbook_path: Path | None,
    model: str,
    work: Path,
) -> dict[str, Any]:
    del work  # reserved for future artifacts
    dev = _run_eval(
        abilities="freshness",
        repeat=2,
        model=model,
        playbook=playbook_path,
        label=f"{name}/dev",
    )
    held = _run_heldout(model=model, playbook=playbook_path, name=name)
    safety = _run_eval(
        abilities="safety",
        repeat=1,
        model=model,
        playbook=playbook_path,
        label=f"{name}/safety",
    )
    return {
        "name": name,
        "dev": _summarize(dev),
        "heldout": _summarize(held),
        "safety": _summarize(safety, safety=True),
        "playbook_path": str(playbook_path) if playbook_path else None,
    }


def _run_heldout(*, model: str, playbook: Path | None, name: str) -> dict[str, Any]:
    """freshness_holdout tasks + web_mitochondria only."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["MINIAI_CHECKER"] = "off"
    env["MINIAI_MODEL"] = model
    if playbook is not None:
        env["MINIAI_PLAYBOOK"] = str(playbook)
    else:
        env.pop("MINIAI_PLAYBOOK", None)
    cmd = [
        sys.executable,
        "-m",
        "eval.run",
        "--suite",
        "full",
        "--model",
        model,
        "--task",
        "fresh_go,fresh_rust,fresh_postgres,web_mitochondria",
        "--repeat",
        "2",
    ]
    print(f"[trial] {name}/heldout: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    json_path = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("JSON:"):
            json_path = Path(line.split("JSON:", 1)[1].strip())
    if json_path is None or not json_path.is_file():
        raise RuntimeError(
            f"heldout eval failed (exit={proc.returncode}). "
            f"stderr:\n{(proc.stderr or '')[-1500:]}"
        )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return {"json_path": str(json_path), "data": data, "exit_code": proc.returncode}


def trial(proposal_dir: Path, *, model: str = EXPECTED_MODEL) -> Path:
    proposal_path = proposal_dir / "proposal.json"
    if not proposal_path.is_file():
        raise FileNotFoundError(proposal_path)
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    accepted = proposal.get("accepted") or []

    playbook_hash_before = _sha256(DEFAULT_PLAYBOOK)
    base_body = _read_playbook_body(DEFAULT_PLAYBOOK)

    work = proposal_dir / "trial_work"
    work.mkdir(parents=True, exist_ok=True)

    # Current playbook (via temp copy so MINIAI_PLAYBOOK is always set consistently)
    current_pb = work / "playbook_current.md"
    _write_temp_playbook(base_body, None, current_pb)
    current = run_variant(
        name="current", playbook_path=current_pb, model=model, work=work
    )

    candidate_rows: list[dict[str, Any]] = []
    for c in accepted:
        cid = c["id"]
        pb = work / f"playbook_{cid}.md"
        _write_temp_playbook(base_body, c["instruction"], pb)
        row = run_variant(name=cid, playbook_path=pb, model=model, work=work)
        row["instruction"] = c["instruction"]
        row["rationale"] = c.get("rationale") or ""
        v, reasons = verdict_for(current, row)
        row["verdict"] = v
        row["verdict_reasons"] = reasons
        candidate_rows.append(row)

    playbook_hash_after = _sha256(DEFAULT_PLAYBOOK)
    if playbook_hash_after != playbook_hash_before:
        raise RuntimeError("prompts/playbook.md changed during trial — aborting")

    # Verify models
    all_models = {current["dev"]["model"], current["heldout"]["model"], current["safety"]["model"]}
    for row in candidate_rows:
        all_models.update(
            {row["dev"]["model"], row["heldout"]["model"], row["safety"]["model"]}
        )
    if all_models != {model}:
        print(f"WARNING: unexpected models seen: {all_models}")

    results = {
        "stamp": proposal.get("stamp") or proposal_dir.name,
        "model": model,
        "playbook_hash": playbook_hash_before,
        "playbook_unchanged": playbook_hash_after == playbook_hash_before,
        "current": current,
        "candidates": candidate_rows,
        "rejected_by_filter": proposal.get("rejected") or [],
    }
    (proposal_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )

    # report.md
    lines = [
        f"# Trial report {results['stamp']}",
        "",
        f"Model: `{model}`",
        f"Playbook hash (unchanged): `{playbook_hash_before}`",
        "",
        "| variant | dev | held-out | safety | mean wall s | verdict |",
        "|---|---:|---:|---|---:|---|",
    ]

    def _wall(row: dict) -> float:
        return round(
            (
                row["dev"]["mean_wall_s"]
                + row["heldout"]["mean_wall_s"]
                + row["safety"]["mean_wall_s"]
            )
            / 3.0,
            3,
        )

    def _row_line(name: str, row: dict, verdict: str) -> str:
        return (
            f"| {name} | {row['dev']['pass_rate']:.0%} "
            f"({row['dev']['passed']}/{row['dev']['total']}) | "
            f"{row['heldout']['pass_rate']:.0%} "
            f"({row['heldout']['passed']}/{row['heldout']['total']}) | "
            f"{row['safety']['safety']} | {_wall(row)} | {verdict} |"
        )

    lines.append(_row_line("current", current, "(baseline)"))
    for row in candidate_rows:
        lines.append(_row_line(row["name"], row, row["verdict"]))
    lines.extend(["", "## Candidates", ""])
    for row in candidate_rows:
        lines.append(f"### {row['name']} — {row['verdict']}")
        lines.append("")
        lines.append(f"- instruction: {row['instruction']}")
        lines.append(f"- rationale: {row['rationale']}")
        if row.get("verdict_reasons"):
            lines.append(f"- reasons: {'; '.join(row['verdict_reasons'])}")
        lines.append("")
    if results["rejected_by_filter"]:
        lines.extend(["## Rejected by filter (not trialled)", ""])
        for c in results["rejected_by_filter"]:
            lines.append(
                f"- **{c['id']}**: {c['instruction']} — {c.get('filter_reason')}"
            )
        lines.append("")
    (proposal_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {proposal_dir / 'report.md'}")
    return proposal_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trial playbook candidates")
    parser.add_argument("proposal_dir", type=Path)
    parser.add_argument("--model", default=EXPECTED_MODEL)
    args = parser.parse_args(argv)
    trial(args.proposal_dir, model=args.model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
