"""Run MiniAI evaluation tasks.

Usage:
    python -m eval.run --suite quick|full [--repeat N] [--save-baseline]
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EVAL_DIR = Path(__file__).resolve().parent
TASKS_DIR = EVAL_DIR / "tasks"
BASELINE_PATH = EVAL_DIR / "baseline.json"
LAST_REPORT_PATH = EVAL_DIR / "last_report.md"
LOGS_DIR = PROJECT_ROOT / "logs"


@dataclass
class EvalContext:
    """Per-task mutable state shared by setup / run / grader / teardown."""

    task_id: str
    ability: str
    temp_root: Path
    state: dict[str, Any] = field(default_factory=dict)
    answers: list[str] = field(default_factory=list)
    transcript_path: Optional[Path] = None
    prompt_log: list[tuple[str, str, str]] = field(default_factory=list)
    model_calls: int = 0
    prompt_tokens: int = 0
    wall_s: float = 0.0
    mode: str = "live"  # live | offline
    # Infrastructure retries after Lemonade/server errors (not task-logic retries).
    infra_retries: int = 0


def _resolve_callable(dotted: str) -> Callable:
    if "." not in dotted:
        mod = importlib.import_module("eval.fixtures")
        return getattr(mod, dotted)
    mod_name, _, attr = dotted.rpartition(".")
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


def _load_tasks(
    suite: str, abilities: Optional[set[str]] = None
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid task file: {path}")
        task_suite = data.get("suite", "full")
        if suite == "quick" and task_suite != "quick":
            continue
        if abilities is not None and data.get("ability") not in abilities:
            continue
        tasks.append(data)
    # Safety first (must pass), then offline, then live (coding last — heavy).
    def _order(t: dict[str, Any]) -> tuple:
        ability = t.get("ability", "")
        mode = t.get("mode", "live")
        tid = t.get("id", "")
        safety_rank = 0 if ability == "safety" else 1
        mode_rank = 0 if mode == "offline" else 1
        coding_rank = 1 if ability == "coding" else 0
        return (safety_rank, mode_rank, coding_rank, tid)

    tasks.sort(key=_order)
    return tasks


def _count_transcript_stats(path: Optional[Path]) -> tuple[int, int]:
    if path is None or not path.is_file():
        return 0, 0
    calls = 0
    tokens = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "tool_call":
            calls += 1
        if ev.get("type") == "model_call":
            calls += 1
            tokens += int(ev.get("prompt_tokens") or 0)
        pt = ev.get("prompt_tokens")
        if pt and ev.get("type") != "model_call":
            tokens += int(pt)
    return calls, tokens


def _wait_for_lemonade(timeout_s: float = 180.0) -> None:
    """Block until Lemonade answers a tiny chat (handles watchdog reloads)."""
    import requests

    from config import settings
    from scripts.agent_loop import _require_lemonade

    _require_lemonade()
    base = settings.LEMONADE_BASE_URL.rstrip("/")
    # BASE_URL already includes /api/v1
    url = f"{base}/chat/completions"
    # Prefer explicitly configured model; fall back to a lighter loaded GGUF.
    candidates = []
    for m in (
        os.environ.get("MINIAI_MODEL") or "",
        settings.LEMONADE_MODEL,
        "Qwen3-14B-GGUF",
        "Qwen3-30B-A3B-GGUF",
    ):
        if m and m not in candidates:
            candidates.append(m)
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        for model in candidates:
            try:
                r = requests.post(
                    url,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Reply OK"}],
                        "max_tokens": 8,
                    },
                    timeout=90,
                )
                if r.status_code == 200:
                    os.environ["MINIAI_MODEL"] = model
                    # Refresh settings module attribute if already imported.
                    settings.LEMONADE_MODEL = model
                    return
                last_err = f"{model}: {r.status_code} {r.text[:160]}"
                if "model_load_error" in (r.text or ""):
                    continue
            except requests.RequestException as exc:
                last_err = f"{model}: {exc}"
                continue
        time.sleep(5)
    raise RuntimeError(f"Lemonade not ready after {timeout_s}s: {last_err}")


def _is_server_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return (
        "500" in text
        or "502" in text
        or "503" in text
        or "backend_watchdog" in text
        or "ReadTimeout" in text
        or "ConnectionError" in text
    )


def _run_live_task(task: dict[str, Any], ctx: EvalContext) -> None:
    import requests

    from tests.support import answer_by_action

    from llm.lemonade.provider import LemonadeProvider
    from scripts.chat import end_session, new_session, run_user_turn
    from security.gate import reset_session
    from tools.browser.browser_tools import close_session

    mapping = dict(task.get("answer_by_action") or {})
    prompts = task.get("prompts") or []
    if isinstance(prompts, str):
        prompts = [prompts]
    # Allow setup() to inject values via ctx.state into prompt templates.
    rendered: list[str] = []
    for prompt in prompts:
        try:
            rendered.append(str(prompt).format(**ctx.state))
        except Exception:
            rendered.append(str(prompt))

    max_attempts = 3
    last_exc: Optional[BaseException] = None
    started = time.perf_counter()
    for attempt in range(max_attempts):
        if attempt > 0:
            ctx.infra_retries += 1
            time.sleep(5)
        _wait_for_lemonade()
        reset_session()
        close_session()
        provider = LemonadeProvider()
        session = new_session(provider)
        ctx.answers = []
        try:
            with answer_by_action(mapping, default="no") as prompt_log:
                for prompt in rendered:
                    answer = run_user_turn(session, prompt)
                    ctx.answers.append(answer or "")
                ctx.prompt_log = list(prompt_log)
            last_exc = None
            break
        except (requests.HTTPError, requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if not _is_server_error(exc) or attempt + 1 >= max_attempts:
                raise
            print(f"[eval] server error on {ctx.task_id}; retrying ({attempt+1})")
        finally:
            if session.transcript is not None:
                ctx.transcript_path = Path(session.transcript.path)
                ctx.model_calls, ctx.prompt_tokens = _count_transcript_stats(
                    ctx.transcript_path
                )
                if session.last_prompt_tokens:
                    ctx.prompt_tokens = max(
                        ctx.prompt_tokens, int(session.last_prompt_tokens)
                    )
            end_session(session)
            close_session()
    ctx.wall_s = time.perf_counter() - started
    if last_exc is not None:
        raise last_exc


def _run_one(task: dict[str, Any]) -> dict[str, Any]:
    from tests.support import use_temp_data

    task_id = task["id"]
    ability = task["ability"]
    mode = task.get("mode", "live")
    temp_root = use_temp_data()
    # Temp browser profile for isolation
    browser_profile = temp_root / "browser_profile"
    browser_profile.mkdir(parents=True, exist_ok=True)
    os.environ["MINIAI_BROWSER_PROFILE"] = str(browser_profile)

    ctx = EvalContext(
        task_id=task_id,
        ability=ability,
        temp_root=temp_root,
        mode=mode,
    )
    setup = _resolve_callable(task["setup"])
    teardown = _resolve_callable(task["teardown"])
    grader = _resolve_callable(task["grader"])

    passed = False
    reason = ""
    err_tb = ""
    try:
        setup(ctx)
        if mode == "live":
            _run_live_task(task, ctx)
        elif mode == "offline":
            started = time.perf_counter()
            # Offline graders do their own work; still record wall later.
            ctx.wall_s = 0.0
            _offline_started = started
        else:
            raise ValueError(f"Unknown mode {mode!r} for task {task_id}")

        ok, reason = grader(ctx)
        if mode == "offline" and ctx.wall_s == 0.0:
            ctx.wall_s = time.perf_counter() - _offline_started
        passed = bool(ok)
        if not reason:
            reason = "ok" if passed else "failed"
    except Exception as exc:
        passed = False
        reason = f"{type(exc).__name__}: {exc}"
        err_tb = traceback.format_exc()
    finally:
        try:
            teardown(ctx)
        except Exception as te:
            if passed:
                passed = False
                reason = f"teardown failed: {te}"
            else:
                reason = f"{reason} | teardown: {te}"

    return {
        "id": task_id,
        "ability": ability,
        "suite": task.get("suite", "full"),
        "mode": mode,
        "pass": passed,
        "reason": reason,
        "wall_s": round(ctx.wall_s, 3),
        "model_calls": ctx.model_calls,
        "prompt_tokens": ctx.prompt_tokens,
        "infra_retries": int(ctx.infra_retries),
        "answers": ctx.answers,
        "error": err_tb,
    }


def _ability_rates(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by: dict[str, list[bool]] = {}
    walls: dict[str, list[float]] = {}
    for r in results:
        by.setdefault(r["ability"], []).append(bool(r["pass"]))
        walls.setdefault(r["ability"], []).append(float(r.get("wall_s") or 0.0))
    out: dict[str, dict[str, Any]] = {}
    for ability, flags in sorted(by.items()):
        n = len(flags)
        p = sum(1 for x in flags if x)
        w = walls.get(ability) or []
        out[ability] = {
            "passed": p,
            "total": n,
            "rate": round(p / n, 4) if n else 0.0,
            "mean_wall_s": round(sum(w) / len(w), 3) if w else 0.0,
        }
    return out


def _safety_headline(results: list[dict[str, Any]]) -> str:
    safety = [r for r in results if r["ability"] == "safety"]
    if not safety:
        return "N/A"
    if all(r["pass"] for r in safety):
        return "PASS"
    return "FAIL"


def _compare_baseline(
    rates: dict[str, dict[str, Any]], baseline: Optional[dict]
) -> list[str]:
    flags: list[str] = []
    if not baseline:
        return flags
    base_rates = baseline.get("ability_rates") or {}
    for ability, info in rates.items():
        prev = base_rates.get(ability)
        if not prev:
            continue
        if info["rate"] < float(prev.get("rate", 0)):
            flags.append(
                f"{ability}: {info['rate']:.0%} < baseline {float(prev['rate']):.0%}"
            )
    return flags


def _write_report(
    *,
    suite: str,
    results: list[dict[str, Any]],
    rates: dict[str, dict[str, Any]],
    safety: str,
    drops: list[str],
    stamp: str,
    json_path: Path,
) -> None:
    lines = [
        f"# Eval report ({suite}) - {stamp}",
        "",
        f"- Results JSON: `{json_path}`",
        f"- Safety headline: **{safety}**",
        f"- Tasks: {sum(1 for r in results if r['pass'])}/{len(results)} passed",
        "",
        "## Per ability",
        "",
        "| Ability | Passed | Total | Rate |",
        "|---|---:|---:|---:|",
    ]
    for ability, info in rates.items():
        lines.append(
            f"| {ability} | {info['passed']} | {info['total']} | {info['rate']:.0%} |"
        )
    lines.extend(["", "## Per task", ""])
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        retries = int(r.get("infra_retries") or 0)
        retry_note = (
            f"; retried after server error: {retries}" if retries else ""
        )
        lines.append(
            f"- **{status}** `{r['id']}` ({r['ability']}) "
            f"{r['wall_s']}s calls={r['model_calls']} tokens={r['prompt_tokens']}"
            f"{retry_note}: {r['reason']}"
        )
    retried = [
        r for r in results if int(r.get("infra_retries") or 0) > 0
    ]
    lines.extend(["", "## Stability", ""])
    if not retried:
        lines.append("- (no infrastructure retries)")
    else:
        for r in retried:
            n = int(r.get("infra_retries") or 0)
            lines.append(
                f"- `{r['id']}`: retried after server error: {n}"
            )
    if drops:
        lines.extend(["", "## Baseline drops", ""])
        for d in drops:
            lines.append(f"- {d}")
    else:
        lines.extend(["", "## Baseline drops", "", "- (none)", ""])
    LAST_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MiniAI Stage 10 evaluation")
    parser.add_argument("--suite", choices=("quick", "full"), required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--ability",
        default=None,
        help="Comma-separated ability filter (e.g. web,knowledge)",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Write eval/baseline.json from this run",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override MINIAI_MODEL for this run (e.g. Qwen3-14B-GGUF)",
    )
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Prefer a loaded model: if the configured default fails to load, fall back.
    if args.model:
        os.environ["MINIAI_MODEL"] = args.model
    else:
        # Ensure config picks up env before provider imports elsewhere.
        os.environ.setdefault("MINIAI_MODEL", os.environ.get("MINIAI_MODEL", ""))

    abilities = None
    if args.ability:
        abilities = {a.strip() for a in args.ability.split(",") if a.strip()}
    tasks = _load_tasks(args.suite, abilities=abilities)
    if not tasks:
        print(f"No tasks found for suite={args.suite} ability={args.ability!r}")
        return 1

    all_results: list[dict[str, Any]] = []
    for rep in range(args.repeat):
        if args.repeat > 1:
            print(f"\n=== repeat {rep + 1}/{args.repeat} ===")
        for task in tasks:
            print(f"\n--- task {task['id']} ({task['ability']}) ---")
            result = _run_one(task)
            status = "PASS" if result["pass"] else "FAIL"
            print(f"{status}: {result['id']} - {result['reason']}")
            all_results.append(result)

    # Aggregate across repeats: a task id fails if any repeat failed.
    by_id: dict[str, list[dict[str, Any]]] = {}
    for r in all_results:
        by_id.setdefault(r["id"], []).append(r)
    summary_results: list[dict[str, Any]] = []
    for task_id, runs in by_id.items():
        merged = dict(runs[0])
        merged["pass"] = all(x["pass"] for x in runs)
        merged["wall_s"] = round(sum(x["wall_s"] for x in runs) / len(runs), 3)
        merged["model_calls"] = sum(x["model_calls"] for x in runs)
        merged["prompt_tokens"] = sum(x["prompt_tokens"] for x in runs)
        merged["infra_retries"] = sum(int(x.get("infra_retries") or 0) for x in runs)
        if not merged["pass"]:
            fails = [x["reason"] for x in runs if not x["pass"]]
            merged["reason"] = fails[0] if fails else merged["reason"]
        summary_results.append(merged)

    rates = _ability_rates(summary_results)
    safety = _safety_headline(summary_results)
    baseline = None
    if BASELINE_PATH.is_file():
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    drops = _compare_baseline(rates, baseline)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = LOGS_DIR / f"eval_{stamp}.json"
    payload = {
        "stamp": stamp,
        "suite": args.suite,
        "repeat": args.repeat,
        "safety": safety,
        "ability_rates": rates,
        "baseline_drops": drops,
        "results": summary_results,
        "raw_runs": all_results,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_report(
        suite=args.suite,
        results=summary_results,
        rates=rates,
        safety=safety,
        drops=drops,
        stamp=stamp,
        json_path=json_path,
    )

    if args.save_baseline:
        if safety != "PASS":
            print(
                "Refusing to save baseline: safety headline is not PASS "
                f"(got {safety})."
            )
        else:
            BASELINE_PATH.write_text(
                json.dumps(
                    {
                        "stamp": stamp,
                        "suite": args.suite,
                        "ability_rates": rates,
                        "safety": safety,
                        "tasks": {
                            r["id"]: {"pass": r["pass"], "ability": r["ability"]}
                            for r in summary_results
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"Wrote baseline {BASELINE_PATH}")

    print(f"\nSafety: {safety}")
    print(f"JSON: {json_path}")
    print(f"Report: {LAST_REPORT_PATH}")
    if drops:
        print("Baseline drops:")
        for d in drops:
            print(f"  - {d}")

    # Exit non-zero if any task failed or safety failed.
    if safety == "FAIL" or any(not r["pass"] for r in summary_results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
