"""Fixed 3-prompt inference benchmark for Lemonade / llama.cpp options.

Reports prompt-processing tok/s, generation tok/s, time-to-first-token, and
peak system RAM. Designed for Round 5 Part 2 (configs A–D).

Usage:
  python -m scripts.bench_infer --label A --runs 3
  python -m scripts.bench_infer --all   # load each config, bench 3x, tool checks
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("LEMONADE_BASE", "http://localhost:13305/api/v1").rstrip("/")
MODEL = os.environ.get("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
MIN_FREE_GB = 3.0

# ~4K-token tool-result summary (chars/4 ≈ tokens)
_TOOL_BLOCK = (
    "<<<BEGIN UNTRUSTED WEB CONTENT>>>\n"
    + ("Python 3.12.10 is the current stable release. " * 200)
    + "\n<<<END UNTRUSTED WEB CONTENT>>>\n"
)
# ~10K-token context
_LONG_CTX = ("Section about local AI agents and tool use. " * 900)

PROMPTS: list[tuple[str, list[dict[str, str]]]] = [
    (
        "short_chat",
        [{"role": "user", "content": "Reply with exactly one short sentence saying hello."}],
    ),
    (
        "tool_summary_4k",
        [
            {
                "role": "system",
                "content": "Summarize the tool result in 2 sentences. Do not invent facts.",
            },
            {
                "role": "user",
                "content": "What Python version does the tool result mention?\n\n" + _TOOL_BLOCK,
            },
        ],
    ),
    (
        "long_context_10k",
        [
            {"role": "system", "content": _LONG_CTX},
            {
                "role": "user",
                "content": "In one sentence, what is this conversation about?",
            },
        ],
    ),
]

CONFIGS: dict[str, dict[str, Any]] = {
    "A": {
        "desc": "current saved (--n-gpu-layers 35)",
        "llamacpp_args": "--n-gpu-layers 35",
    },
    "B": {
        "desc": "all layers on GPU (--n-gpu-layers 99)",
        "llamacpp_args": "--n-gpu-layers 99",
    },
    "C": {
        "desc": "B + KV q8_0 + flash-attn",
        "llamacpp_args": "--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on",
    },
}


def _ram() -> dict[str, float]:
    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / (1024**3), 3),
        "used_gb": round((vm.total - vm.available) / (1024**3), 3),
        "avail_gb": round(vm.available / (1024**3), 3),
    }


def _lemonade(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["lemonade", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def free_ram_ok(need_extra_gb: float = 0.0) -> tuple[bool, float]:
    avail = _ram()["avail_gb"]
    return avail - need_extra_gb >= MIN_FREE_GB, avail


class PeakRamSampler:
    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self.peak_used = 0.0
        self.min_avail = 1e9
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.peak_used = _ram()["used_gb"]
        self.min_avail = _ram()["avail_gb"]
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.wait(self.interval):
                r = _ram()
                self.peak_used = max(self.peak_used, r["used_gb"])
                self.min_avail = min(self.min_avail, r["avail_gb"])

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, float]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        return {
            "peak_used_gb": round(self.peak_used, 3),
            "min_avail_gb": round(self.min_avail, 3),
        }


def unload() -> None:
    _lemonade("unload")


def load_model(llamacpp_args: str, *, save: bool = False) -> dict[str, Any]:
    """Unload, check free RAM, load MODEL with ctx 16384 + args."""
    unload()
    time.sleep(2)
    ok, avail = free_ram_ok()
    if not ok:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"free RAM {avail:.2f} GB < {MIN_FREE_GB} GB before load",
            "avail_gb": avail,
        }
    cmd = [
        "load",
        MODEL,
        "--ctx-size",
        "16384",
        "--llamacpp-args",
        llamacpp_args,
    ]
    if save:
        cmd.append("--save-options")
    print(f"LOAD: lemonade {' '.join(cmd)}", flush=True)
    proc = _lemonade(*cmd, timeout=900)
    out = (proc.stdout or "") + (proc.stderr or "")
    loaded = proc.returncode == 0 and "error" not in out.lower()
    # Confirm via status
    st = _lemonade("status")
    status_txt = (st.stdout or "") + (st.stderr or "")
    ready = MODEL in status_txt and "ready" in status_txt.lower()
    ram = _ram()
    if ram["avail_gb"] < MIN_FREE_GB:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"after load free RAM {ram['avail_gb']:.2f} GB < {MIN_FREE_GB}",
            "avail_gb": ram["avail_gb"],
            "load_out": out[-500:],
            "status": status_txt[-500:],
        }
    return {
        "ok": bool(loaded or ready),
        "skipped": False,
        "returncode": proc.returncode,
        "avail_gb": ram["avail_gb"],
        "used_gb": ram["used_gb"],
        "load_out": out[-800:],
        "status": status_txt[-800:],
    }


def find_draft_gguf() -> Optional[Path]:
    """Locate Qwen3-0.6B GGUF on disk after lemonade pull."""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    matches = list(hub.glob("**/Qwen3-0.6B*.gguf"))
    if not matches:
        matches = list(hub.glob("**/*0.6B*.gguf"))
    if not matches:
        return None
    # Prefer Q4-class
    matches.sort(key=lambda p: (0 if "Q4" in p.name else 1, p.stat().st_size))
    return matches[0]


def ensure_draft_model() -> Optional[Path]:
    path = find_draft_gguf()
    if path and path.is_file():
        return path
    print("PULL: Qwen3-0.6B-GGUF (draft)", flush=True)
    proc = _lemonade("pull", "Qwen3-0.6B-GGUF", timeout=1800)
    print((proc.stdout or "")[-400:], flush=True)
    return find_draft_gguf()


def one_prompt_bench(messages: list[dict[str, str]], max_tokens: int = 64) -> dict[str, Any]:
    """Stream one completion; return TTFT + timings + peak RAM during call."""
    sampler = PeakRamSampler()
    sampler.start()
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.perf_counter()
    ttft: Optional[float] = None
    content_parts: list[str] = []
    timings: dict[str, Any] = {}
    usage: dict[str, Any] = {}
    error: Optional[str] = None
    try:
        with requests.post(
            f"{BASE}/chat/completions",
            json=payload,
            stream=True,
            timeout=600,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                line = raw.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if chunk.get("timings"):
                    timings = chunk["timings"]
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    content_parts.append(piece)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - t0
    ram = sampler.stop()
    pp = timings.get("prompt_per_second")
    gen = timings.get("predicted_per_second")
    return {
        "ttft_s": round(ttft, 4) if ttft is not None else None,
        "wall_s": round(wall, 3),
        "pp_tok_s": round(float(pp), 3) if pp is not None else None,
        "gen_tok_s": round(float(gen), 3) if gen is not None else None,
        "prompt_n": timings.get("prompt_n"),
        "predicted_n": timings.get("predicted_n"),
        "usage": usage,
        "timings": timings,
        "content_preview": "".join(content_parts)[:120],
        "error": error,
        **ram,
    }


def run_bench(runs: int = 3) -> dict[str, Any]:
    results: dict[str, Any] = {"model": MODEL, "runs": [], "by_prompt": {}}
    overall_peak = 0.0
    overall_min_avail = 1e9
    for run_i in range(runs):
        run_row: dict[str, Any] = {"run": run_i + 1, "prompts": {}}
        for name, messages in PROMPTS:
            print(f"  bench run={run_i+1} prompt={name}", flush=True)
            row = one_prompt_bench(messages)
            run_row["prompts"][name] = row
            if row.get("peak_used_gb"):
                overall_peak = max(overall_peak, row["peak_used_gb"])
            if row.get("min_avail_gb") is not None:
                overall_min_avail = min(overall_min_avail, row["min_avail_gb"])
            print(
                f"    ttft={row.get('ttft_s')} pp={row.get('pp_tok_s')} "
                f"gen={row.get('gen_tok_s')} peak_ram={row.get('peak_used_gb')} "
                f"err={row.get('error')}",
                flush=True,
            )
        results["runs"].append(run_row)
    # Aggregate means across runs×prompts for headline numbers
    def _mean(key: str) -> Optional[float]:
        vals = []
        for run in results["runs"]:
            for row in run["prompts"].values():
                v = row.get(key)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
        return round(sum(vals) / len(vals), 3) if vals else None

    per_prompt: dict[str, Any] = {}
    for name, _ in PROMPTS:
        vals = {
            "ttft_s": [],
            "pp_tok_s": [],
            "gen_tok_s": [],
            "peak_used_gb": [],
            "min_avail_gb": [],
        }
        for run in results["runs"]:
            row = run["prompts"][name]
            for k in vals:
                if isinstance(row.get(k), (int, float)):
                    vals[k].append(float(row[k]))
        per_prompt[name] = {
            k: (round(sum(v) / len(v), 3) if v else None) for k, v in vals.items()
        }
    results["by_prompt"] = per_prompt
    results["mean"] = {
        "ttft_s": _mean("ttft_s"),
        "pp_tok_s": _mean("pp_tok_s"),
        "gen_tok_s": _mean("gen_tok_s"),
        "peak_used_gb": round(overall_peak, 3),
        "min_avail_gb": round(overall_min_avail, 3)
        if overall_min_avail < 1e8
        else None,
    }
    results["errors"] = [
        (r["run"], n, row["error"])
        for r in results["runs"]
        for n, row in r["prompts"].items()
        if row.get("error")
    ]
    return results


def run_tool_checks() -> dict[str, Any]:
    """Run web_python_version and coding_wordcount once via eval."""
    from tests.support import use_temp_data

    use_temp_data()
    out: dict[str, Any] = {}
    for task in ("web_python_version", "coding_wordcount"):
        print(f"  tool-check: {task}", flush=True)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.run",
                "--suite",
                "quick",
                "--task",
                task,
                "--model",
                MODEL,
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=900,
            encoding="utf-8",
            errors="replace",
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        passed = "PASS" in text and "FAIL" not in text.split(task)[-1][:200]
        # Heuristic: look for task line
        ok_line = None
        for line in text.splitlines():
            if task in line and ("PASS" in line or "FAIL" in line or "pass" in line.lower()):
                ok_line = line.strip()
                break
        out[task] = {
            "returncode": proc.returncode,
            "wall_s": round(time.perf_counter() - t0, 1),
            "summary_line": ok_line,
            "tail": text[-600:],
        }
        print(f"    {task}: rc={proc.returncode} line={ok_line}", flush=True)
    return out


def build_config_d_args(base_args: str) -> Optional[str]:
    """Build speculative-decoding args.

    Note: Lemonade reserves ``--model-draft`` / ``-md`` and rejects them inside
    ``--llamacpp-args``. Until Lemonade exposes a first-class draft flag, D
    cannot be loaded through the normal load path; callers should treat a
    None / load failure as \"skipped — Lemonade manages draft\".
    """
    draft = ensure_draft_model()
    if draft is None:
        return None
    # Still attempt with -md for the record; load_model will surface Lemonade's
    # reserved-argument error if blocked.
    draft_s = str(draft).replace("\\", "/")
    return f"{base_args} -md {draft_s} --spec-draft-n-max 4"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", help="Single config label A/B/C/D")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--all", action="store_true", help="Run A–D full protocol")
    ap.add_argument("--skip-tools", action="store_true")
    ap.add_argument("--save-best", action="store_true")
    ap.add_argument(
        "--out",
        default=str(
            ROOT
            / "logs"
            / f"bench_infer_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        ),
    )
    args = ap.parse_args()

    # Resolve D after knowing best of A–C when --all
    report: dict[str, Any] = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL,
        "configs": {},
        "chosen": None,
    }

    labels = ["A", "B", "C", "D"] if args.all else [args.label or "A"]
    best_of_abc: Optional[str] = None
    best_score = -1.0
    abc_args_for_d = CONFIGS["B"]["llamacpp_args"]

    for label in labels:
        if label == "D":
            # Best of A–C for speculative base
            base = (
                CONFIGS[best_of_abc]["llamacpp_args"]
                if best_of_abc and best_of_abc in CONFIGS
                else abc_args_for_d
            )
            # Prefer C's KV if C won, else B's ngl
            draft_args = build_config_d_args(base)
            if draft_args is None:
                report["configs"]["D"] = {
                    "skipped": True,
                    "reason": "draft model Qwen3-0.6B GGUF not available",
                }
                print("SKIP D: no draft model", flush=True)
                continue
            cfg = {
                "desc": f"best-of-ABC + speculative draft ({best_of_abc or 'B'})",
                "llamacpp_args": draft_args,
            }
        else:
            cfg = CONFIGS[label]

        print(f"\n=== CONFIG {label}: {cfg['desc']} ===", flush=True)
        load_res = load_model(cfg["llamacpp_args"], save=False)
        entry: dict[str, Any] = {
            "desc": cfg["desc"],
            "llamacpp_args": cfg["llamacpp_args"],
            "load": load_res,
        }
        if load_res.get("skipped") or not load_res.get("ok"):
            entry["skipped"] = True
            entry["reason"] = load_res.get("reason") or "load failed"
            report["configs"][label] = entry
            print(f"SKIP {label}: {entry['reason']}", flush=True)
            continue

        bench = run_bench(runs=args.runs)
        entry["bench"] = bench
        if not args.skip_tools:
            try:
                entry["tool_checks"] = run_tool_checks()
            except Exception as exc:
                entry["tool_checks"] = {"error": str(exc)}

        # Eligibility: no bench errors, min_avail >= 3, tools didn't crash hard
        eligible = not bench.get("errors")
        min_avail = (bench.get("mean") or {}).get("min_avail_gb")
        if min_avail is not None and min_avail < MIN_FREE_GB:
            eligible = False
            entry["disqualify"] = f"min_avail_gb={min_avail} < {MIN_FREE_GB}"
        entry["eligible"] = eligible
        gen = (bench.get("mean") or {}).get("gen_tok_s") or 0.0
        ttft = (bench.get("mean") or {}).get("ttft_s") or 999.0
        # Score: prefer higher gen tok/s, then lower TTFT
        score = float(gen) * 1000.0 - float(ttft)
        entry["score"] = score
        report["configs"][label] = entry

        if label in ("A", "B", "C") and eligible and score > best_score:
            best_score = score
            best_of_abc = label
            abc_args_for_d = cfg["llamacpp_args"]

    # Pick overall winner among eligible
    winner = None
    win_score = -1e18
    for label, entry in report["configs"].items():
        if entry.get("skipped") or not entry.get("eligible"):
            continue
        sc = entry.get("score") or -1e18
        if sc > win_score:
            win_score = sc
            winner = label
    report["chosen"] = winner
    if winner and args.save_best:
        args_str = report["configs"][winner]["llamacpp_args"]
        print(f"\nSAVE-OPTIONS winner={winner}: {args_str}", flush=True)
        save_res = load_model(args_str, save=True)
        report["save"] = save_res
        # Verify export
        exp = _lemonade("export", MODEL)
        report["export_after_save"] = (exp.stdout or "")[-1000:]

    report["finished"] = datetime.now().isoformat(timespec="seconds")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWROTE {out_path}", flush=True)
    print(f"CHOSEN={winner}", flush=True)

    # Print table
    print("\nconfig | pp tok/s | gen tok/s | TTFT | peak RAM | min free | eligible")
    for label, entry in report["configs"].items():
        if entry.get("skipped"):
            print(f"{label} | SKIP: {entry.get('reason')}")
            continue
        m = (entry.get("bench") or {}).get("mean") or {}
        print(
            f"{label} | {m.get('pp_tok_s')} | {m.get('gen_tok_s')} | "
            f"{m.get('ttft_s')} | {m.get('peak_used_gb')} | "
            f"{m.get('min_avail_gb')} | {entry.get('eligible')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
