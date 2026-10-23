"""Trial playbook candidates against dev, held-out, and safety evals.

Stage 12b-fix: per-run scoring, source failures in the dev set, interleaved
variants, margin-based verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from prompts.playbook_loader import DEFAULT_PLAYBOOK, PLAYBOOK_MAX_CHARS

EXPECTED_MODEL = "Qwen3-30B-A3B-GGUF"

# Canonical freshness task ids (ability: freshness).
FRESHNESS_TASK_IDS = (
    "fresh_firefox",
    "fresh_linux_kernel",
    "fresh_node_lts",
    "fresh_python",
)

HOLDOUT_TASK_IDS = (
    "fresh_go",
    "fresh_rust",
    "fresh_postgres",
    "web_mitochondria",
)


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


def source_failed_task_ids(proposal: dict[str, Any]) -> list[str]:
    """Task ids that failed in the proposal's source eval (dev sets only)."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in proposal.get("failures") or []:
        tid = str(row.get("task_id") or "")
        if tid and tid not in seen:
            seen.add(tid)
            ids.append(tid)
    # Also scan source eval JSON if present.
    src = proposal.get("source_eval")
    if src:
        path = Path(src)
        if not path.is_file():
            path = PROJECT_ROOT / src
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            for r in data.get("raw_runs") or data.get("results") or []:
                if r.get("pass") is False:
                    tid = str(r.get("id") or "")
                    if tid and tid not in seen:
                        seen.add(tid)
                        ids.append(tid)
    return ids


def build_dev_task_ids(proposal: dict[str, Any]) -> list[str]:
    """Failed tasks from the source eval PLUS all freshness tasks."""
    failed = source_failed_task_ids(proposal)
    combined = set(FRESHNESS_TASK_IDS) | set(failed)
    return sorted(combined)


def interleaved_schedule(
    variant_names: list[str], n_repeats: int
) -> list[tuple[int, str]]:
    """(repeat_index, variant_name) with variants nested inside repeats."""
    return [(rep, name) for rep in range(n_repeats) for name in variant_names]


def score_raw_runs(raw_runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-run score: ERROR excluded from pass/fail totals."""
    errors = [r for r in raw_runs if r.get("pass") is None]
    scored = [r for r in raw_runs if r.get("pass") is not None]
    passed = sum(1 for r in scored if r.get("pass") is True)
    failed = sum(1 for r in scored if r.get("pass") is False)
    walls = [float(r.get("wall_s") or 0.0) for r in raw_runs]
    mean_wall = sum(walls) / len(walls) if walls else 0.0
    by_task: dict[str, dict[str, int]] = {}
    for r in raw_runs:
        tid = str(r.get("id") or "")
        slot = by_task.setdefault(tid, {"passed": 0, "failed": 0, "errors": 0, "runs": 0})
        slot["runs"] += 1
        if r.get("pass") is None:
            slot["errors"] += 1
        elif r.get("pass") is True:
            slot["passed"] += 1
        else:
            slot["failed"] += 1
    models = sorted(
        {str(r.get("model") or "") for r in raw_runs if r.get("model")} 
        # raw runs may not carry model; caller adds top-level
    )
    return {
        "passed": passed,
        "failed": failed,
        "total": len(scored),
        "error_count": len(errors),
        "errors": [
            {
                "id": e.get("id"),
                "reason": e.get("reason"),
            }
            for e in errors
        ],
        "mean_wall_s": round(mean_wall, 3),
        "by_task": by_task,
        "models": models,
        "raw_runs": raw_runs,
    }


def mean_wall_for_variant(row: dict[str, Any]) -> float:
    parts = [
        float(row["dev"].get("mean_wall_s") or 0.0),
        float(row["heldout"].get("mean_wall_s") or 0.0),
        float(row["safety"].get("mean_wall_s") or 0.0),
    ]
    return round(sum(parts) / 3.0, 3)


def verdict_for(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[str, list[str]]:
    """Margin-based verdict using per-run pass counts.

    ACCEPTABLE if:
      - cand_dev_passes >= current_dev_passes + 2
      - cand_heldout >= current_heldout - 1
        (if exactly -1 → 'ACCEPTABLE (held-out -1, review)')
      - safety 100%
      - mean wall <= current × 1.2
    """
    reasons: list[str] = []
    review_tag = False

    c_dev = int(candidate["dev"]["passed"])
    b_dev = int(current["dev"]["passed"])
    if c_dev < b_dev + 2:
        reasons.append(
            f"dev passes {c_dev} < current {b_dev} + 2 (need >= {b_dev + 2})"
        )

    c_hold = int(candidate["heldout"]["passed"])
    b_hold = int(current["heldout"]["passed"])
    if c_hold < b_hold - 1:
        reasons.append(
            f"held-out passes {c_hold} < current {b_hold} - 1 "
            f"(need >= {b_hold - 1})"
        )
    elif c_hold == b_hold - 1:
        review_tag = True

    if candidate["safety"].get("safety") != "PASS":
        reasons.append(
            f"safety not 100% (got {candidate['safety'].get('safety')})"
        )

    cur_wall = mean_wall_for_variant(current)
    cand_wall = mean_wall_for_variant(candidate)
    if cand_wall > cur_wall * 1.2 + 1e-9:
        reasons.append(
            f"mean wall {cand_wall:.3f} > current×1.2 ({cur_wall * 1.2:.3f})"
        )

    if reasons:
        return "REJECTED", reasons
    if review_tag:
        return "ACCEPTABLE (held-out -1, review)", [
            f"held-out passes {c_hold} == current {b_hold} - 1"
        ]
    return "ACCEPTABLE", []


def _run_eval_once(
    *,
    task_ids: list[str] | None,
    abilities: str | None,
    model: str,
    playbook: Path | None,
    label: str,
    repeat: int = 1,
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
        "--repeat",
        str(repeat),
    ]
    if task_ids is not None:
        cmd.extend(["--task", ",".join(task_ids)])
    if abilities is not None:
        cmd.extend(["--ability", abilities])
    print(f"[trial] {label}: {' '.join(cmd)} playbook={playbook}", flush=True)
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
            f"eval failed for {label} (exit={proc.returncode}). "
            f"stderr tail:\n{(proc.stderr or '')[-1500:]}\n"
            f"stdout tail:\n{(proc.stdout or '')[-1500:]}"
        )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    top_model = str(data.get("model") or "")
    if top_model != model:
        raise RuntimeError(
            f"ERROR: unexpected model {top_model!r} (want {model!r}) for {label}"
        )
    return {
        "json_path": str(json_path),
        "data": data,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
    }


def _merge_scores(blobs: list[dict[str, Any]], *, safety: bool = False) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    json_paths: list[str] = []
    models: set[str] = set()
    for blob in blobs:
        data = blob["data"]
        models.add(str(data.get("model") or ""))
        json_paths.append(blob["json_path"])
        for r in data.get("raw_runs") or data.get("results") or []:
            row = dict(r)
            row.setdefault("model", data.get("model"))
            raw.append(row)
    scored = score_raw_runs(raw)
    scored["models"] = sorted(models)
    scored["json_paths"] = json_paths
    if safety:
        # Safety headline: all safety runs must pass (no ERROR, no fail).
        safety_rows = [r for r in raw if r.get("ability") == "safety"]
        if not safety_rows:
            safety_rows = raw
        ok = (
            all(r.get("pass") is True for r in safety_rows)
            and len(safety_rows) > 0
        )
        scored["safety"] = "PASS" if ok else "FAIL"
        scored["safety_ok"] = ok
    return scored


def _empty_variant(name: str, playbook_path: Path | None) -> dict[str, Any]:
    empty = score_raw_runs([])
    return {
        "name": name,
        "dev": dict(empty),
        "heldout": dict(empty),
        "safety": {**empty, "safety": "FAIL", "safety_ok": False},
        "playbook_path": str(playbook_path) if playbook_path else None,
        "status": "ok",
        "status_reason": "",
    }


def trial(
    proposal_dir: Path,
    *,
    model: str = EXPECTED_MODEL,
    repeat_dev: int = 3,
    repeat_holdout: int = 2,
) -> Path:
    proposal_path = proposal_dir / "proposal.json"
    if not proposal_path.is_file():
        raise FileNotFoundError(proposal_path)
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    accepted = proposal.get("accepted") or []

    playbook_hash_before = _sha256(DEFAULT_PLAYBOOK)
    base_body = _read_playbook_body(DEFAULT_PLAYBOOK)

    work = proposal_dir / "trial_work"
    work.mkdir(parents=True, exist_ok=True)

    # Variant playbooks
    variants: list[tuple[str, Path, dict[str, Any] | None]] = []
    current_pb = work / "playbook_current.md"
    _write_temp_playbook(base_body, None, current_pb)
    variants.append(("current", current_pb, None))
    for c in accepted:
        cid = str(c["id"])
        pb = work / f"playbook_{cid}.md"
        _write_temp_playbook(base_body, c.get("instruction"), pb)
        variants.append((cid, pb, c))

    variant_names = [v[0] for v in variants]
    playbooks = {v[0]: v[1] for v in variants}
    meta = {v[0]: v[2] for v in variants}

    dev_tasks = build_dev_task_ids(proposal)
    print(f"[trial] dev tasks: {dev_tasks}", flush=True)
    print(f"[trial] holdout tasks: {list(HOLDOUT_TASK_IDS)}", flush=True)
    print(
        f"[trial] variants={variant_names} "
        f"repeat_dev={repeat_dev} repeat_holdout={repeat_holdout}",
        flush=True,
    )

    # Accumulators: variant -> list of eval blobs
    dev_blobs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    hold_blobs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    safety_blobs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    variant_errors: dict[str, str] = {}

    # --- Dev: interleaved ---
    for rep, vname in interleaved_schedule(variant_names, repeat_dev):
        if vname in variant_errors:
            continue
        try:
            blob = _run_eval_once(
                task_ids=dev_tasks,
                abilities=None,
                model=model,
                playbook=playbooks[vname],
                label=f"{vname}/dev/r{rep + 1}",
                repeat=1,
            )
            # Per-run model check already in _run_eval_once; also scan raw
            for r in blob["data"].get("raw_runs") or []:
                # no per-run model field normally; top-level checked
                pass
            dev_blobs[vname].append(blob)
        except Exception as exc:
            variant_errors[vname] = str(exc)
            print(f"[trial] ERROR aborting variant {vname}: {exc}", flush=True)

    # --- Held-out: interleaved ---
    for rep, vname in interleaved_schedule(variant_names, repeat_holdout):
        if vname in variant_errors:
            continue
        try:
            blob = _run_eval_once(
                task_ids=list(HOLDOUT_TASK_IDS),
                abilities=None,
                model=model,
                playbook=playbooks[vname],
                label=f"{vname}/heldout/r{rep + 1}",
                repeat=1,
            )
            hold_blobs[vname].append(blob)
        except Exception as exc:
            variant_errors[vname] = str(exc)
            print(f"[trial] ERROR aborting variant {vname}: {exc}", flush=True)

    # --- Safety: once per variant ---
    for vname in variant_names:
        if vname in variant_errors:
            continue
        try:
            blob = _run_eval_once(
                task_ids=None,
                abilities="safety",
                model=model,
                playbook=playbooks[vname],
                label=f"{vname}/safety",
                repeat=1,
            )
            safety_blobs[vname].append(blob)
        except Exception as exc:
            variant_errors[vname] = str(exc)
            print(f"[trial] ERROR aborting variant {vname}: {exc}", flush=True)

    playbook_hash_after = _sha256(DEFAULT_PLAYBOOK)
    if playbook_hash_after != playbook_hash_before:
        raise RuntimeError("prompts/playbook.md changed during trial — aborting")

    # Build variant rows
    rows: dict[str, dict[str, Any]] = {}
    for vname in variant_names:
        if vname in variant_errors:
            row = _empty_variant(vname, playbooks[vname])
            row["status"] = "ERROR"
            row["status_reason"] = variant_errors[vname]
            row["verdict"] = "ERROR"
            row["verdict_reasons"] = [variant_errors[vname]]
        else:
            row = {
                "name": vname,
                "dev": _merge_scores(dev_blobs[vname]),
                "heldout": _merge_scores(hold_blobs[vname]),
                "safety": _merge_scores(safety_blobs[vname], safety=True),
                "playbook_path": str(playbooks[vname]),
                "status": "ok",
                "status_reason": "",
            }
            # Abort-style ERROR if any unexpected model slipped through
            seen_models = set(row["dev"].get("models") or [])
            seen_models |= set(row["heldout"].get("models") or [])
            seen_models |= set(row["safety"].get("models") or [])
            seen_models.discard("")
            if seen_models and seen_models != {model}:
                row["status"] = "ERROR"
                row["status_reason"] = f"unexpected models: {sorted(seen_models)}"
                row["verdict"] = "ERROR"
                row["verdict_reasons"] = [row["status_reason"]]
        if meta[vname]:
            row["instruction"] = meta[vname].get("instruction") or ""
            row["rationale"] = meta[vname].get("rationale") or ""
        rows[vname] = row

    current = rows["current"]
    candidate_rows: list[dict[str, Any]] = []
    for vname in variant_names:
        if vname == "current":
            continue
        row = rows[vname]
        if row.get("verdict") != "ERROR":
            v, reasons = verdict_for(current, row)
            row["verdict"] = v
            row["verdict_reasons"] = reasons
        candidate_rows.append(row)

    # Per-task breakdown across variants
    task_breakdown: list[dict[str, Any]] = []
    all_task_ids = sorted(
        set(dev_tasks) | set(HOLDOUT_TASK_IDS)
    )
    for tid in all_task_ids:
        for vname in variant_names:
            row = rows[vname]
            # Prefer suite that contains the task
            for suite_key in ("dev", "heldout", "safety"):
                by = (row.get(suite_key) or {}).get("by_task") or {}
                if tid in by:
                    slot = by[tid]
                    scored = slot["passed"] + slot["failed"]
                    task_breakdown.append(
                        {
                            "task": tid,
                            "variant": vname,
                            "passed": slot["passed"],
                            "runs": scored,
                            "errors": slot["errors"],
                            "suite": suite_key,
                        }
                    )
                    break

    results = {
        "stamp": proposal.get("stamp") or proposal_dir.name,
        "model": model,
        "repeat_dev": repeat_dev,
        "repeat_holdout": repeat_holdout,
        "dev_task_ids": dev_tasks,
        "holdout_task_ids": list(HOLDOUT_TASK_IDS),
        "playbook_hash": playbook_hash_before,
        "playbook_unchanged": playbook_hash_after == playbook_hash_before,
        "current": current,
        "candidates": candidate_rows,
        "rejected_by_filter": proposal.get("rejected") or [],
        "task_breakdown": task_breakdown,
        "interleave_dev": [
            {"repeat": r, "variant": v}
            for r, v in interleaved_schedule(variant_names, repeat_dev)
        ],
        "interleave_holdout": [
            {"repeat": r, "variant": v}
            for r, v in interleaved_schedule(variant_names, repeat_holdout)
        ],
    }
    (proposal_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )

    # --- report.md ---
    lines = [
        f"# Trial report {results['stamp']} (Stage 12b-fix)",
        "",
        f"Model expected: `{model}`",
        f"Playbook hash (unchanged): `{playbook_hash_before}`",
        f"Dev tasks: `{', '.join(dev_tasks)}`",
        f"Held-out tasks: `{', '.join(HOLDOUT_TASK_IDS)}`",
        f"Repeats: dev={repeat_dev}, holdout={repeat_holdout}",
        "",
        "## Per-variant run counts",
        "",
        "| variant | status | models | dev passes/runs | held-out passes/runs | "
        "safety | ERROR runs | mean wall s | verdict |",
        "|---|---|---|---:|---:|---|---:|---:|---|",
    ]

    def _line(name: str, row: dict, verdict: str) -> str:
        models = sorted(
            set(row["dev"].get("models") or [])
            | set(row["heldout"].get("models") or [])
            | set(row["safety"].get("models") or [])
        )
        err_n = (
            int(row["dev"].get("error_count") or 0)
            + int(row["heldout"].get("error_count") or 0)
            + int(row["safety"].get("error_count") or 0)
        )
        return (
            f"| {name} | {row.get('status', 'ok')} | "
            f"{', '.join(models) or model} | "
            f"{row['dev']['passed']}/{row['dev']['total']} | "
            f"{row['heldout']['passed']}/{row['heldout']['total']} | "
            f"{row['safety'].get('safety')} | {err_n} | "
            f"{mean_wall_for_variant(row)} | {verdict} |"
        )

    lines.append(_line("current", current, "(baseline)"))
    for row in candidate_rows:
        lines.append(_line(row["name"], row, row.get("verdict", "")))

    # ERROR runs listed separately
    lines.extend(["", "## ERROR runs (excluded from pass/fail)", ""])
    any_err = False
    for vname in variant_names:
        row = rows[vname]
        for suite in ("dev", "heldout", "safety"):
            for e in (row.get(suite) or {}).get("errors") or []:
                any_err = True
                lines.append(
                    f"- **{vname}/{suite}** `{e.get('id')}`: {e.get('reason')}"
                )
        if row.get("status") == "ERROR":
            any_err = True
            lines.append(f"- **{vname}** variant ERROR: {row.get('status_reason')}")
    if not any_err:
        lines.append("- (none)")

    lines.extend(["", "## Per-task breakdown", ""])
    lines.append("| task | variant | passes/runs | suite |")
    lines.append("|---|---|---:|---|")
    for tb in task_breakdown:
        lines.append(
            f"| {tb['task']} | {tb['variant']} | "
            f"{tb['passed']}/{tb['runs']} | {tb['suite']} |"
        )

    lines.extend(["", "## Candidates", ""])
    for row in candidate_rows:
        lines.append(f"### {row['name']} — {row.get('verdict')}")
        lines.append("")
        lines.append(f"- instruction: {row.get('instruction', '')}")
        lines.append(f"- rationale: {row.get('rationale', '')}")
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
    print(f"Wrote {proposal_dir / 'report.md'}", flush=True)
    return proposal_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trial playbook candidates")
    parser.add_argument("proposal_dir", type=Path)
    parser.add_argument("--model", default=EXPECTED_MODEL)
    parser.add_argument("--repeat-dev", type=int, default=3)
    parser.add_argument("--repeat-holdout", type=int, default=2)
    args = parser.parse_args(argv)
    trial(
        args.proposal_dir,
        model=args.model,
        repeat_dev=args.repeat_dev,
        repeat_holdout=args.repeat_holdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
