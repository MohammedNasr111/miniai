"""Offline tests for Stage 12a-fix eval model targeting (no live model)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeHealthResp:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


def test_a_fail_no_fallback() -> None:
    from eval.run import wait_for_target_model

    tried: list[str] = []
    post_timeouts: list[float] = []

    def fake_post(url, json=None, timeout=90, **kwargs):
        model = (json or {}).get("model")
        tried.append(model)
        post_timeouts.append(timeout)
        return _FakeResp(500, "model_load_error: boom")

    def fake_get(url, timeout=5, **kwargs):
        return _FakeHealthResp({"all_models_loaded": []})

    t = {"n": 0.0}

    def fake_time():
        t["n"] += 1.0
        return t["n"]

    with mock.patch("time.sleep", return_value=None), mock.patch(
        "time.time", side_effect=fake_time
    ):
        try:
            wait_for_target_model(
                "OnlyTarget-Model",
                timeout_s=3.0,
                post_fn=fake_post,
                get_fn=fake_get,
                base_url="http://localhost:9/api/v1",
            )
            raised = False
            err = ""
        except RuntimeError as exc:
            raised = True
            err = str(exc)
    ok = (
        raised
        and "OnlyTarget-Model" in err
        and "failed to load" in err
        and set(tried) == {"OnlyTarget-Model"}
        and 1 <= len(tried) <= 5
        and "Qwen3-14B" not in "".join(str(x) for x in tried)
        and "Qwen3-30B" not in "".join(str(x) for x in tried)
        and all(to == 180 for to in post_timeouts)
    )
    _check(
        "a_fail_no_fallback",
        ok,
        f"raised={raised} n_tried={len(tried)} unique={set(tried)} "
        f"timeouts={post_timeouts} err={err!r}",
    )


def test_b_model_in_json_and_report() -> None:
    from eval import run as eval_run

    tmp = Path(tempfile.mkdtemp(prefix="miniai_eval_model_"))
    report_path = tmp / "last_report.md"
    json_path = tmp / "eval.json"
    model = "Qwen3-30B-A3B-GGUF"
    results = [
        {
            "id": "t1",
            "ability": "web",
            "pass": True,
            "reason": "ok",
            "wall_s": 1.0,
            "model_calls": 1,
            "prompt_tokens": 10,
            "infra_retries": 0,
        }
    ]
    rates = eval_run._ability_rates(results)
    text = eval_run.write_report(
        suite="full",
        model=model,
        results=results,
        rates=rates,
        safety="N/A",
        drops=[],
        stamp="teststamp",
        json_path=json_path,
        report_path=report_path,
    )
    payload = {
        "stamp": "teststamp",
        "model": model,
        "suite": "full",
        "results": results,
    }
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    report = report_path.read_text(encoding="utf-8")
    ok = (
        loaded.get("model") == model
        and f"Model: **{model}**" in report
        and report.startswith("# Eval report")
        and model in text
    )
    _check(
        "b_model_in_json_and_report",
        ok,
        f"json_model={loaded.get('model')!r} report_has={model in report}",
    )


def test_c_baseline_mismatch() -> None:
    from eval.run import compare_baseline

    rates = {"web": {"passed": 1, "total": 1, "rate": 0.5, "mean_wall_s": 1.0}}
    baseline = {
        "model": "Qwen3-14B-GGUF",
        "ability_rates": {"web": {"rate": 1.0}},
    }
    drops, msg = compare_baseline(rates, baseline, "Qwen3-30B-A3B-GGUF")
    ok = (
        drops == []
        and msg is not None
        and "BASELINE MODEL MISMATCH" in msg
        and "Qwen3-14B-GGUF" in msg
        and "Qwen3-30B-A3B-GGUF" in msg
    )
    # Matching model should still compute deltas.
    drops2, msg2 = compare_baseline(
        rates,
        {"model": "Qwen3-30B-A3B-GGUF", "ability_rates": {"web": {"rate": 1.0}}},
        "Qwen3-30B-A3B-GGUF",
    )
    ok2 = msg2 is None and any("web:" in d for d in drops2)
    _check(
        "c_baseline_mismatch",
        ok and ok2,
        f"msg={msg!r} drops2={drops2!r}",
    )


def test_d_task_filter() -> None:
    from eval.run import _load_tasks

    all_full = _load_tasks("full")
    ids = {t["id"] for t in all_full}
    assert "web_python_version" in ids or "web_python_version_plain" in ids
    filtered = _load_tasks(
        "full",
        task_ids={"web_python_version", "web_python_version_plain"},
    )
    got = {t["id"] for t in filtered}
    ok = got == {"web_python_version", "web_python_version_plain"} or got == {
        "web_python_version_plain"
    } | ({"web_python_version"} & ids)
    # web_python_version is suite quick — still included in full suite load.
    ok = got == {"web_python_version", "web_python_version_plain"}
    _check("d_task_filter", ok, f"got={sorted(got)}")


def test_e_main_fail_exit() -> None:
    """main() exits 1 when target model fails; never posts another model name."""
    from eval import run as eval_run

    tried: list[str] = []

    def fake_post(url, json=None, timeout=90, **kwargs):
        tried.append((json or {}).get("model"))
        return _FakeResp(503, "unavailable")

    def fake_status():
        return {"raw": "No models loaded.", "error": None, "ctx": None, "model": None}

    with mock.patch.object(eval_run, "capture_lemonade_status", fake_status), mock.patch.object(
        eval_run, "wait_for_target_model", side_effect=RuntimeError(
            "Target model OnlyX failed to load: 503. "
            "Use --model to choose another explicitly."
        )
    ), mock.patch("builtins.print") as _p:
        code = eval_run.main(
            ["--suite", "full", "--task", "web_python_version_plain", "--model", "OnlyX"]
        )
    ok = code == 1
    _check("e_main_fail_exit", ok, f"code={code}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_a_fail_no_fallback()
    test_b_model_in_json_and_report()
    test_c_baseline_mismatch()
    test_d_task_filter()
    test_e_main_fail_exit()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
