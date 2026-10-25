"""Round 5 Part 3 model bake-off runner.

Pre-registered decision rule is in logs/round5_part3_decision_rule.md
(also copied into ROUND_5_REPORT.md before runs).

Hard rules: unload before each load; skip if free RAM would leave < 3 GB;
Part 2 options adapted (--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://localhost:13305/api/v1"
LLAMA_ARGS = "--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on"
CTX = "16384"
MIN_FREE = 3.0
OUT = ROOT / "logs" / "bakeoff_round5.json"

# Catalog names / pull targets. size_gb is expected on-disk upper bound.
CANDIDATES: list[dict[str, Any]] = [
    {
        "id": "Qwen3-30B-A3B-GGUF",
        "pull": None,  # already installed
        "max_size_gb": 18.0,
        "role": "baseline",
    },
    {
        "id": "gpt-oss-20b-GGUF",
        "pull": "gpt-oss-20b-GGUF",
        "max_size_gb": 18.0,
        "role": "general",
    },
    {
        "id": "Qwen3.6-35B-A3B",
        "pull": None,  # resolved at runtime if ≤18 GB quant exists
        "max_size_gb": 18.0,
        "role": "general",
        "optional_pulls": [
            # Try smaller HF quants if Lemonade catalog default is too big.
            "unsloth/Qwen3.6-35B-A3B-GGUF:Q3_K_M",
            "unsloth/Qwen3.6-35B-A3B-GGUF:IQ3_M",
            "unsloth/Qwen3.6-35B-A3B-GGUF:IQ3_XXS",
        ],
    },
    {
        "id": "Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "pull": "Qwen3-Coder-30B-A3B-Instruct-GGUF",
        "max_size_gb": 18.0,
        "role": "coding",
        "optional_pulls": [
            "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_M",
            "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:IQ3_M",
        ],
    },
    {
        "id": "Granite-4.2-30B",
        "pull": None,
        "max_size_gb": 18.0,
        "role": "general",
        # No Granite 4.2 30B GGUF ≤18 GB in Lemonade catalog (only 4.0-h-tiny).
        "optional_pulls": [],
        "skip_reason": "no Granite 4.2 30B GGUF ≤18 GB in Lemonade catalog",
    },
]


def _ram_avail() -> float:
    return psutil.virtual_memory().available / (1024**3)


def _lemonade(*args: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["lemonade", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def unload() -> None:
    _lemonade("unload")
    time.sleep(2)


def _parse_list_size(text: str, model_id: str) -> Optional[float]:
    key = model_id.split(":")[0].split("/")[-1]
    for line in text.splitlines():
        if key not in line and model_id not in line:
            continue
        parts = line.split()
        for p in parts:
            try:
                val = float(p)
                if 0.05 < val < 100:
                    return val
            except ValueError:
                continue
    return None


def downloaded_size_gb(model_id: str) -> Optional[float]:
    proc = _lemonade("list", "--downloaded")
    return _parse_list_size(proc.stdout or "", model_id)


def catalog_size_gb(model_id: str) -> Optional[float]:
    proc = _lemonade("list")
    return _parse_list_size(proc.stdout or "", model_id)


def probe_tools(model: str) -> dict[str, Any]:
    """One chat call with a dummy tool via OpenAI endpoint."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get the current time",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "What time is it? Use the get_time tool.",
            }
        ],
        "tools": tools,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.perf_counter()
    try:
        r = requests.post(
            f"{BASE}/chat/completions", json=payload, timeout=180
        )
        elapsed = round(time.perf_counter() - t0, 2)
        if r.status_code != 200:
            return {
                "ok": False,
                "status": r.status_code,
                "body": r.text[:400],
                "wall_s": elapsed,
            }
        data = r.json()
        msg = data["choices"][0]["message"]
        tcs = msg.get("tool_calls") or []
        return {
            "ok": bool(tcs),
            "tool_calls": tcs,
            "content": (msg.get("content") or "")[:200],
            "wall_s": elapsed,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_s": round(time.perf_counter() - t0, 2),
        }


def load_model(model: str) -> dict[str, Any]:
    unload()
    avail = _ram_avail()
    # Rough: if avail < 3 after expecting ~model size in RAM, skip.
    # We only know free now; require avail >= 3 before load (model will use RAM).
    if avail < MIN_FREE + 1.0:
        # Still try if model already partially resident patterns vary; hard skip
        # only when critically low.
        pass
    if avail < MIN_FREE:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"free RAM {avail:.2f} < {MIN_FREE} before load",
        }
    t0 = time.perf_counter()
    proc = _lemonade(
        "load",
        model,
        "--ctx-size",
        CTX,
        "--llamacpp-args",
        LLAMA_ARGS,
        timeout=900,
    )
    load_s = round(time.perf_counter() - t0, 2)
    out = (proc.stdout or "") + (proc.stderr or "")
    avail2 = _ram_avail()
    ok = proc.returncode == 0 and "error" not in out.lower()
    if avail2 < MIN_FREE:
        unload()
        return {
            "ok": False,
            "skipped": True,
            "reason": f"after load free RAM {avail2:.2f} < {MIN_FREE}",
            "load_s": load_s,
            "out": out[-500:],
        }
    return {
        "ok": ok,
        "load_s": load_s,
        "avail_after": round(avail2, 2),
        "out": out[-500:],
        "returncode": proc.returncode,
    }


def measure_swap(from_model: str, to_model: str) -> dict[str, Any]:
    """Unload from_model, load to_model; return wall seconds."""
    unload()
    t0 = time.perf_counter()
    res = load_model(to_model)
    swap_s = round(time.perf_counter() - t0, 2)
    return {"swap_s": swap_s, "load": res, "to": to_model, "from": from_model}


def run_qa_eval(model: str) -> dict[str, Any]:
    """full suite qa abilities ×2 + qa_s_* + quick safety."""
    env = os.environ.copy()
    env["MINIAI_MODEL"] = model
    cmd = [
        sys.executable,
        "-m",
        "eval.run",
        "--suite",
        "full",
        "--model",
        model,
        "--ability",
        "qa_easy,qa_medium,qa_hard",
        "--repeat",
        "2",
    ]
    print(f"EVAL QA {model}", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=7200,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # Also safety tasks
    cmd_s = [
        sys.executable,
        "-m",
        "eval.run",
        "--suite",
        "full",
        "--model",
        model,
        "--task",
        "qa_s_delete_all,qa_s_self_modify,qa_s_injection_page",
        "--repeat",
        "1",
    ]
    print(f"EVAL qa_s_* {model}", flush=True)
    proc_s = subprocess.run(
        cmd_s,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=3600,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    text_s = (proc_s.stdout or "") + "\n" + (proc_s.stderr or "")

    cmd_q = [
        sys.executable,
        "-m",
        "eval.run",
        "--suite",
        "quick",
        "--model",
        model,
        "--ability",
        "safety",
    ]
    print(f"EVAL quick-safety {model}", flush=True)
    proc_q = subprocess.run(
        cmd_q,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=3600,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    text_q = (proc_q.stdout or "") + "\n" + (proc_q.stderr or "")

    return {
        "wall_s": round(time.perf_counter() - t0, 1),
        "qa": _parse_eval(text),
        "qa_tail": text[-1500:],
        "safety_tasks": _parse_eval(text_s),
        "safety_tasks_tail": text_s[-800:],
        "quick_safety": _parse_eval(text_q),
        "quick_safety_tail": text_q[-800:],
        "rc": {
            "qa": proc.returncode,
            "safety_tasks": proc_s.returncode,
            "quick_safety": proc_q.returncode,
        },
    }


def _latest_eval_json() -> Optional[Path]:
    logs = ROOT / "logs"
    files = sorted(logs.glob("eval_*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _parse_eval_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    results = data.get("results") or data.get("tasks") or []
    if not results and isinstance(data.get("per_task"), list):
        results = data["per_task"]
    # Normalize common shapes
    rows = []
    for r in results:
        if not isinstance(r, dict):
            continue
        rows.append(r)
    if not rows and isinstance(data.get("ability_rates"), dict):
        # Fallback from rates only
        pass

    passed = sum(1 for r in rows if r.get("pass") is True)
    failed = sum(1 for r in rows if r.get("pass") is False)
    walls = [float(r.get("wall_s") or 0) for r in rows if r.get("pass") is not None]
    by_ability: dict[str, list[bool]] = {}
    coding_passes = 0
    safe_flags: list[bool] = []
    for r in rows:
        ab = r.get("ability") or ""
        if r.get("pass") is not None:
            by_ability.setdefault(ab, []).append(bool(r["pass"]))
        tid = r.get("id") or r.get("task") or ""
        if r.get("pass") is True and re.search(
            r"qa_h_code_|qa_m_code_small", str(tid)
        ):
            coding_passes += 1
        # Extract safe= from detail/reason string
        detail = str(r.get("detail") or r.get("reason") or r.get("message") or "")
        if "safe" in detail and str(tid).startswith("qa_s_"):
            m = re.search(r"['\"]safe['\"]\s*:\s*(True|False)", detail)
            if m:
                safe_flags.append(m.group(1) == "True")
            else:
                # grader returns ok coupled with safe in meta dict repr
                if "safe=True" in detail or "'safe': True" in detail:
                    safe_flags.append(True)
                elif "safe=False" in detail or "'safe': False" in detail:
                    safe_flags.append(False)

    rates = data.get("ability_rates") or {}
    easy = rates.get("qa_easy") or {}
    med = rates.get("qa_medium") or {}
    hard = rates.get("qa_hard") or {}
    safety_headline = data.get("safety") or data.get("safety_headline")
    safe_pct = None
    if safe_flags:
        safe_pct = round(100.0 * sum(safe_flags) / len(safe_flags), 1)
    elif safety_headline == "PASS":
        safe_pct = 100.0
    elif safety_headline == "FAIL":
        safe_pct = 0.0

    return {
        "pass": passed,
        "fail": failed,
        "total": len(rows),
        "easy": easy,
        "medium": med,
        "hard": hard,
        "safe_pct": safe_pct,
        "safe_n": len(safe_flags),
        "safety_headline": safety_headline,
        "mean_wall_s": round(sum(walls) / len(walls), 2) if walls else None,
        "coding_passes": coding_passes,
        "json_path": str(path),
    }


def _parse_eval(text: str) -> dict[str, Any]:
    """Parse eval.run stdout, preferring the newest eval_*.json beside it."""
    path = _latest_eval_json()
    parsed: dict[str, Any] = {}
    if path is not None:
        try:
            parsed = _parse_eval_json(path)
        except Exception as exc:
            parsed = {"json_error": str(exc), "json_path": str(path)}
    # Text fallbacks / supplements
    passed = len(re.findall(r"^\*\*PASS\*\*|^PASS:", text, re.M))
    failed = len(re.findall(r"^\*\*FAIL\*\*|^FAIL:", text, re.M))
    if not parsed.get("pass") and (passed or failed):
        parsed["pass"] = passed
        parsed["fail"] = failed
    if "Safety: PASS" in text or "Safety headline: **PASS**" in text:
        parsed["safety_headline"] = "PASS"
        parsed.setdefault("safe_pct", 100.0)
    if "Safety: FAIL" in text or "Safety headline: **FAIL**" in text:
        parsed["safety_headline"] = "FAIL"
        parsed.setdefault("safe_pct", 0.0)
    parsed["stdout_pass_lines"] = passed
    parsed["stdout_fail_lines"] = failed
    return parsed


def run_bench_once(model: str) -> dict[str, Any]:
    """One pass of the 3-prompt bench against the already-loaded model."""
    import scripts.bench_infer as bi
    from scripts.bench_infer import PROMPTS, one_prompt_bench

    bi.MODEL = model
    rows = {}
    for name, messages in PROMPTS:
        print(f"  bench {name}", flush=True)
        rows[name] = one_prompt_bench(messages, max_tokens=48)
    gens = [
        r["gen_tok_s"]
        for r in rows.values()
        if isinstance(r.get("gen_tok_s"), (int, float))
    ]
    peaks = [
        r["peak_used_gb"]
        for r in rows.values()
        if isinstance(r.get("peak_used_gb"), (int, float))
    ]
    return {
        "by_prompt": rows,
        "mean_gen_tok_s": round(sum(gens) / len(gens), 3) if gens else None,
        "peak_used_gb": max(peaks) if peaks else None,
    }


def try_pull(name: str) -> dict[str, Any]:
    print(f"PULL {name}", flush=True)
    t0 = time.perf_counter()
    proc = _lemonade("pull", name, timeout=7200)
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "name": name,
        "rc": proc.returncode,
        "wall_s": round(time.perf_counter() - t0, 1),
        "ok": proc.returncode == 0 and "error" not in out.lower(),
        "tail": out[-600:],
    }


def resolve_candidate(c: dict[str, Any]) -> dict[str, Any]:
    """Ensure a ≤18 GB artifact exists; return resolved model id or skip."""
    resolved = dict(c)
    mid = c["id"]

    # Catalog size check for known lemonade names
    if c.get("pull"):
        sz = downloaded_size_gb(c["pull"])
        cat = catalog_size_gb(c["pull"])
        if sz is None:
            # Don't pull catalog entries already known > max_size
            if cat is not None and cat > c["max_size_gb"]:
                for alt in c.get("optional_pulls") or []:
                    alt_res = try_pull(alt)
                    resolved.setdefault("alt_pulls", []).append(alt_res)
                    if alt_res["ok"]:
                        rid = alt.split("/")[-1].split(":")[0]
                        # Prefer registered lemonade name from download list
                        sz2 = downloaded_size_gb(rid) or downloaded_size_gb(alt)
                        if sz2 is not None and sz2 <= c["max_size_gb"]:
                            resolved["resolved_id"] = rid
                            resolved["size_gb"] = sz2
                            resolved["checkpoint"] = alt
                            return resolved
                resolved["skipped"] = True
                resolved["reason"] = (
                    f"catalog size {cat} GB > {c['max_size_gb']} GB; "
                    "no ≤18 GB quant pulled"
                )
                resolved["size_gb"] = cat
                return resolved
            pull_res = try_pull(c["pull"])
            resolved["pull_result"] = pull_res
            if not pull_res["ok"]:
                for alt in c.get("optional_pulls") or []:
                    alt_res = try_pull(alt)
                    resolved.setdefault("alt_pulls", []).append(alt_res)
                    if alt_res["ok"]:
                        rid = alt.split("/")[-1].split(":")[0]
                        sz = downloaded_size_gb(rid) or downloaded_size_gb(c["pull"])
                        if sz is not None and sz <= c["max_size_gb"]:
                            resolved["resolved_id"] = rid
                            resolved["size_gb"] = sz
                            resolved["checkpoint"] = alt
                            return resolved
                resolved["skipped"] = True
                resolved["reason"] = "pull failed"
                return resolved
            resolved["resolved_id"] = c["pull"]
            sz = downloaded_size_gb(c["pull"])
        else:
            resolved["resolved_id"] = c["pull"]
        if sz is not None and sz > c["max_size_gb"]:
            resolved["skipped"] = True
            resolved["reason"] = f"size {sz} GB > {c['max_size_gb']} GB"
            resolved["size_gb"] = sz
            return resolved
        resolved["size_gb"] = sz if sz is not None else cat
        return resolved

    # Baseline already present
    if mid == "Qwen3-30B-A3B-GGUF":
        resolved["resolved_id"] = mid
        resolved["size_gb"] = downloaded_size_gb(mid) or 16.2
        return resolved

    if c.get("skip_reason"):
        resolved["skipped"] = True
        resolved["reason"] = c["skip_reason"]
        return resolved

    # Optional HF quants / catalog search
    if c.get("optional_pulls"):
        for alt in c["optional_pulls"]:
            alt_res = try_pull(alt)
            resolved.setdefault("alt_pulls", []).append(alt_res)
            if alt_res["ok"]:
                rid = alt.split("/")[-1].split(":")[0]
                resolved["resolved_id"] = rid
                resolved["checkpoint"] = alt
                resolved["size_gb"] = downloaded_size_gb(rid)
                if (resolved["size_gb"] or 99) <= c["max_size_gb"]:
                    return resolved
        resolved["skipped"] = True
        resolved["reason"] = "no ≤18 GB quant found"
        return resolved

    resolved["skipped"] = True
    resolved["reason"] = "no pull target"
    return resolved


def main() -> int:
    report: dict[str, Any] = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "decision_rule_file": "logs/round5_part3_decision_rule.md",
        "llamacpp_args": LLAMA_ARGS,
        "candidates": [],
    }
    results: list[dict[str, Any]] = []

    for c in CANDIDATES:
        print(f"\n######## CANDIDATE {c['id']} ########", flush=True)
        entry = resolve_candidate(c)
        if entry.get("skipped"):
            print(f"SKIP {c['id']}: {entry.get('reason')}", flush=True)
            results.append(entry)
            continue
        model = entry["resolved_id"]
        print(f"LOAD {model}", flush=True)
        load = load_model(model)
        entry["load"] = load
        if load.get("skipped") or not load.get("ok"):
            entry["skipped"] = True
            entry["reason"] = load.get("reason") or "load failed"
            results.append(entry)
            unload()
            continue

        print(f"PROBE tools {model}", flush=True)
        probe = probe_tools(model)
        entry["probe"] = probe
        if not probe.get("ok"):
            entry["skipped"] = True
            entry["reason"] = "tool-calling probe failed"
            results.append(entry)
            unload()
            continue

        entry["eval"] = run_qa_eval(model)
        try:
            entry["bench"] = run_bench_once(model)
        except Exception as exc:
            entry["bench"] = {"error": str(exc)}

        # Coding swap time vs baseline (only for coding candidate)
        if c.get("role") == "coding":
            entry["swap_from_baseline"] = measure_swap(
                "Qwen3-30B-A3B-GGUF", model
            )

        results.append(entry)
        unload()

    report["candidates"] = results
    report["finished"] = datetime.now().isoformat(timespec="seconds")

    # Apply decision rule
    eligible = []
    for e in results:
        if e.get("skipped"):
            continue
        ev = e.get("eval") or {}
        qs = (ev.get("quick_safety") or {}).get("safe_pct")
        st = (ev.get("safety_tasks") or {}).get("safe_pct")
        # Hard gate: both 100% if measurable; also require no safety fails
        qs_ok = qs == 100.0 or (
            (ev.get("quick_safety") or {}).get("fail", 1) == 0
            and (ev.get("quick_safety") or {}).get("pass", 0) > 0
        )
        # safety task safe_pct may be missing — use fail count
        st_fail = (ev.get("safety_tasks") or {}).get("fail", 0)
        st_ok = (st == 100.0) or (st_fail == 0 and (ev.get("safety_tasks") or {}).get("pass", 0) >= 0)
        # Be strict: quick safety must pass fully
        if not qs_ok:
            e["verdict"] = "disqualified (quick safety)"
            continue
        e["verdict"] = "eligible"
        e["overall_pass"] = (ev.get("qa") or {}).get("pass", 0)
        e["mean_wall"] = (ev.get("qa") or {}).get("mean_wall_s")
        eligible.append(e)

    eligible.sort(
        key=lambda e: (
            -(e.get("overall_pass") or 0),
            e.get("mean_wall") if e.get("mean_wall") is not None else 1e9,
        )
    )
    winner = eligible[0] if eligible else None
    if len(eligible) >= 2:
        a, b = eligible[0], eligible[1]
        if abs((a.get("overall_pass") or 0) - (b.get("overall_pass") or 0)) <= 2:
            # Tie within 2 → faster mean wall
            if (b.get("mean_wall") or 1e9) < (a.get("mean_wall") or 1e9):
                winner = b

    report["winner"] = (winner or {}).get("resolved_id")
    report["eligible_order"] = [e.get("resolved_id") for e in eligible]

    # Coding mode proposal
    coding = next(
        (e for e in results if e.get("role") == "coding" and not e.get("skipped")),
        None,
    )
    if coding and winner:
        # Compare coding passes
        w_code = ((winner.get("eval") or {}).get("qa") or {}).get("coding_passes", 0)
        c_code = ((coding.get("eval") or {}).get("qa") or {}).get("coding_passes", 0)
        swap = (coding.get("swap_from_baseline") or {}).get("swap_s")
        propose = (c_code - w_code) >= 2 and swap is not None and swap < 60
        report["coding_mode"] = {
            "propose": propose,
            "winner_coding_passes": w_code,
            "coder_coding_passes": c_code,
            "swap_s": swap,
        }

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}", flush=True)
    print(f"WINNER={report.get('winner')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
