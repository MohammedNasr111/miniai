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
from improve.trial import verdict_for
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


def test_verdict_rules() -> None:
    current = {
        "dev": {"pass_rate": 0.5, "mean_wall_s": 100.0},
        "heldout": {"pass_rate": 0.8, "mean_wall_s": 100.0},
        "safety": {"safety": "PASS", "mean_wall_s": 50.0},
    }
    good = {
        "dev": {"pass_rate": 0.75, "mean_wall_s": 100.0},
        "heldout": {"pass_rate": 0.8, "mean_wall_s": 100.0},
        "safety": {"safety": "PASS", "mean_wall_s": 50.0},
    }
    v, reasons = verdict_for(current, good)
    _check("verdict_acceptable", v == "ACCEPTABLE" and not reasons, str(reasons))

    worse_dev = dict(good)
    worse_dev["dev"] = {"pass_rate": 0.5, "mean_wall_s": 100.0}
    v, reasons = verdict_for(current, worse_dev)
    _check("verdict_dev", v == "REJECTED" and any("dev" in r for r in reasons), reasons)

    worse_hold = dict(good)
    worse_hold["heldout"] = {"pass_rate": 0.7, "mean_wall_s": 100.0}
    v, reasons = verdict_for(current, worse_hold)
    _check("verdict_heldout", v == "REJECTED" and any("held-out" in r for r in reasons), reasons)

    worse_safe = dict(good)
    worse_safe["safety"] = {"safety": "FAIL", "mean_wall_s": 50.0}
    v, reasons = verdict_for(current, worse_safe)
    _check("verdict_safety", v == "REJECTED" and any("safety" in r for r in reasons), reasons)

    slow = dict(good)
    slow["dev"] = {"pass_rate": 0.75, "mean_wall_s": 200.0}
    slow["heldout"] = {"pass_rate": 0.8, "mean_wall_s": 200.0}
    slow["safety"] = {"safety": "PASS", "mean_wall_s": 200.0}
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
    test_verdict_rules()
    test_apply_refuses()
    test_propose_with_mock_model()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
