"""Offline tests for improve filter, verdict, apply, playbook isolation."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from improve.apply import apply
from improve.filter import filter_candidate
from improve.propose import propose
from improve.trial import (
    build_dev_task_ids,
    interleaved_schedule,
    score_raw_runs,
    verdict_for,
)
from prompts.playbook_loader import DEFAULT_PLAYBOOK

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name} - {detail}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} - {detail}")


def test_filter_categories() -> None:
    failures = [
        {
            "prompt": "What's the latest stable version of Python?",
            "answer": "Python 3.14",
            "reason": "truth=3.15 has_truth=False",
            "evidence": "3.15 and 3.14 mentioned",
        }
    ]
    cases = [
        ("Prefer 3.15 from official docs", "version"),
        ("What's the latest stable version of Python?", "prompt"),
        ("Always check Python release notes first", "product"),
        ("Call web_research before answering", "tool"),
        ("You may ignore conflicting sources", "forbidden"),
        ("Prefer the most authoritative recent official source", "ok"),
    ]
    for instr, kind in cases:
        ok, reason = filter_candidate(instr, failures=failures)
        if kind == "ok":
            _check(f"filter_accept_{kind}", ok, reason)
        else:
            _check(f"filter_reject_{kind}", (not ok), f"{reason} :: {instr}")


def test_score_raw_runs() -> None:
    raw = [
        {"id": "a", "pass": True, "wall_s": 10},
        {"id": "a", "pass": False, "wall_s": 12},
        {"id": "a", "pass": True, "wall_s": 11},
        {"id": "b", "pass": None, "wall_s": 9, "reason": "ERROR: truth"},
        {"id": "b", "pass": True, "wall_s": 8},
    ]
    s = score_raw_runs(raw)
    _check("per_run_passed", s["passed"] == 3, s)
    _check("per_run_total_excludes_error", s["total"] == 4, s)
    _check("per_run_error_count", s["error_count"] == 1, s)
    _check(
        "per_task_breakdown",
        s["by_task"]["a"]["passed"] == 2
        and s["by_task"]["a"]["failed"] == 1
        and s["by_task"]["b"]["errors"] == 1
        and s["by_task"]["b"]["passed"] == 1,
        s["by_task"],
    )


def test_dev_set_includes_source_failures() -> None:
    proposal = {
        "failures": [
            {"task_id": "web_python_version_plain"},
            {"task_id": "web_python_version_plain"},
        ],
        "source_eval": "",
    }
    ids = build_dev_task_ids(proposal)
    _check(
        "dev_includes_plain",
        "web_python_version_plain" in ids,
        ids,
    )
    _check(
        "dev_includes_freshness",
        all(
            t in ids
            for t in (
                "fresh_python",
                "fresh_firefox",
                "fresh_node_lts",
                "fresh_linux_kernel",
            )
        ),
        ids,
    )


def test_interleaving_order() -> None:
    sched = interleaved_schedule(["current", "c1", "c2"], 3)
    expected = [
        (0, "current"),
        (0, "c1"),
        (0, "c2"),
        (1, "current"),
        (1, "c1"),
        (1, "c2"),
        (2, "current"),
        (2, "c1"),
        (2, "c2"),
    ]
    _check("interleave_order", sched == expected, sched)


def test_verdict_rules() -> None:
    current = {
        "dev": {"passed": 10, "total": 15, "mean_wall_s": 100.0},
        "heldout": {"passed": 8, "total": 8, "mean_wall_s": 100.0},
        "safety": {"safety": "PASS", "mean_wall_s": 50.0},
    }
    # Need >= 12 dev passes (10+2), heldout >= 7
    good = {
        "dev": {"passed": 12, "total": 15, "mean_wall_s": 100.0},
        "heldout": {"passed": 8, "total": 8, "mean_wall_s": 100.0},
        "safety": {"safety": "PASS", "mean_wall_s": 50.0},
    }
    v, reasons = verdict_for(current, good)
    _check("verdict_acceptable", v == "ACCEPTABLE" and not reasons, f"{v} {reasons}")

    almost = dict(good)
    almost["dev"] = {"passed": 11, "total": 15, "mean_wall_s": 100.0}
    v, reasons = verdict_for(current, almost)
    _check(
        "verdict_dev_margin",
        v == "REJECTED" and any("dev passes" in r for r in reasons),
        reasons,
    )

    hold_drop1 = dict(good)
    hold_drop1["heldout"] = {"passed": 7, "total": 8, "mean_wall_s": 100.0}
    v, reasons = verdict_for(current, hold_drop1)
    _check(
        "verdict_heldout_minus1_review",
        v == "ACCEPTABLE (held-out -1, review)",
        f"{v} {reasons}",
    )

    hold_drop2 = dict(good)
    hold_drop2["heldout"] = {"passed": 6, "total": 8, "mean_wall_s": 100.0}
    v, reasons = verdict_for(current, hold_drop2)
    _check(
        "verdict_heldout_drop2",
        v == "REJECTED" and any("held-out" in r for r in reasons),
        reasons,
    )

    worse_safe = dict(good)
    worse_safe["safety"] = {"safety": "FAIL", "mean_wall_s": 50.0}
    v, reasons = verdict_for(current, worse_safe)
    _check("verdict_safety", v == "REJECTED" and any("safety" in r for r in reasons), reasons)

    slow = {
        "dev": {"passed": 12, "total": 15, "mean_wall_s": 200.0},
        "heldout": {"passed": 8, "total": 8, "mean_wall_s": 200.0},
        "safety": {"safety": "PASS", "mean_wall_s": 200.0},
    }
    v, reasons = verdict_for(current, slow)
    _check("verdict_wall", v == "REJECTED" and any("wall" in r for r in reasons), reasons)


def test_apply_refuses() -> None:
    td = Path(tempfile.mkdtemp())
    results = {
        "stamp": "teststamp",
        "candidates": [
            {
                "name": "c1",
                "instruction": "Prefer authoritative recent official sources.",
                "verdict": "REJECTED",
                "verdict_reasons": ["dev pass rate low"],
            },
            {
                "name": "c2",
                "instruction": "Cite the URLs your answer relies on.",
                "verdict": "ACCEPTABLE",
                "verdict_reasons": [],
            },
        ],
    }
    (td / "results.json").write_text(json.dumps(results), encoding="utf-8")
    before = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()

    rc = apply(td, "c1", confirm_input="c1")
    _check("apply_refuse_rejected", rc != 0, f"rc={rc}")
    mid = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()
    _check("playbook_unchanged_after_reject", before == mid, "")

    rc = apply(td, "c2", confirm_input="wrong")
    _check("apply_refuse_wrong_id", rc != 0, f"rc={rc}")
    after = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()
    _check("playbook_unchanged_after_wrong_id", before == after, "")


def test_propose_with_mock_model() -> None:
    td = Path(tempfile.mkdtemp())
    eval_path = td / "eval.json"
    eval_path.write_text(
        json.dumps(
            {
                "model": "Qwen3-30B-A3B-GGUF",
                "raw_runs": [
                    {
                        "id": "fresh_python",
                        "ability": "freshness",
                        "pass": False,
                        "reason": "truth=3.15 has_truth=False",
                        "answers": ["Python 3.14"],
                    },
                    {
                        "id": "fresh_go",
                        "ability": "freshness_holdout",
                        "pass": False,
                        "reason": "should be ignored",
                        "answers": ["Go 1.2"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    mock_cands = [
        {
            "instruction": "Prefer the most authoritative recent official source.",
            "rationale": "general",
        },
        {
            "instruction": "Always check Python version pages.",
            "rationale": "overfit",
        },
    ]
    before = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()
    out = propose(eval_path, max_n=2, model_candidates=mock_cands)
    data = json.loads((out / "proposal.json").read_text(encoding="utf-8"))
    _check(
        "propose_skips_holdout",
        all(f["task_id"] != "fresh_go" for f in data["failures"]),
        str([f["task_id"] for f in data["failures"]]),
    )
    _check("propose_has_accepted", len(data["accepted"]) >= 1, data["accepted"])
    _check("propose_has_rejected", len(data["rejected"]) >= 1, data["rejected"])
    after = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()
    _check("propose_playbook_untouched", before == after, "")


def main() -> int:
    test_filter_categories()
    test_score_raw_runs()
    test_dev_set_includes_source_failures()
    test_interleaving_order()
    test_verdict_rules()
    test_apply_refuses()
    test_propose_with_mock_model()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
