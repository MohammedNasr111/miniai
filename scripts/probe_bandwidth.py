"""Round 9 Part 6: is this PC bandwidth-bound?

Loads installed Qwen3-14B-GGUF and Qwen3-30B-A3B-GGUF with production options,
runs a 512-token generation ×3 each, estimates effective GB/s, writes
logs/round9_bandwidth.md (+ .json). Restores Qwen3-30B-A3B-GGUF and checks Hi.
Does not close user apps. No purchase recommendation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")

PROD_MODEL = "Qwen3-30B-A3B-GGUF"
MODELS = ("Qwen3-14B-GGUF", "Qwen3-30B-A3B-GGUF")
CTX = "16384"
LLAMA_ARGS = "--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on --parallel 1"
GEN_TOKENS = 512
REPEATS = 3
DDR5_ONE_CHANNEL_GBS = 44.8
# MoE active/total params (Qwen3-30B-A3B public figures ≈ 3.3B active / 30.5B total).
MOE_ACTIVE = 3.3
MOE_TOTAL = 30.5
FIXED_PROMPT = (
    "Write a long, detailed technical essay explaining how virtual memory, "
    "paging, and the TLB work on a modern PC. Keep going with concrete "
    "examples until you are stopped."
)


def _lemonade(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    from config.proc import hidden_subprocess_kwargs

    return subprocess.run(
        ["lemonade", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(),
    )


def _unload() -> None:
    try:
        _lemonade("unload", "--all", timeout=120)
    except Exception:
        _lemonade("unload", timeout=120)
    time.sleep(2)


def _load(model: str) -> dict[str, Any]:
    _unload()
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
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0 and "error" not in out.lower(),
        "load_s": round(time.perf_counter() - t0, 2),
        "returncode": proc.returncode,
        "out_tail": out[-800:],
    }


def _find_gguf(model: str) -> Optional[Path]:
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    key = model.replace("-GGUF", "")
    matches = list(hub.glob(f"**/*{key}*.gguf"))
    if not matches:
        matches = list(hub.glob(f"**/*{model}*.gguf"))
    if not matches:
        # Prefer Q4_0 for 30B from health path pattern
        matches = list(hub.glob("**/Qwen3-30B-A3B-Q4_0.gguf")) if "30B" in model else []
        matches += list(hub.glob("**/Qwen3-14B*.gguf")) if "14B" in model else []
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_size, reverse=True)
    return matches[0]


def _gpu_split() -> dict[str, Any]:
    from scripts.probe_system import _gpu_adapter_memory

    return _gpu_adapter_memory()


def _open_apps_note() -> dict[str, Any]:
    from agent.perf_probe import free_ram_gb, top_processes_by_rss, total_ram_gb

    return {
        "free_ram_gb": free_ram_gb(),
        "total_ram_gb": total_ram_gb(),
        "top_processes": top_processes_by_rss(15),
        "note": "User apps left open; nothing was closed for this probe.",
    }


def _gen_once(model: str) -> dict[str, Any]:
    import requests
    from config import settings

    url = f"{settings.LEMONADE_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": FIXED_PROMPT}],
        "max_tokens": GEN_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.perf_counter()
    r = requests.post(url, json=payload, timeout=600)
    wall = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    timings = data.get("timings") or {}
    completion = int(usage.get("completion_tokens") or 0)
    tok_s = None
    if isinstance(timings, dict) and timings.get("predicted_per_second"):
        tok_s = float(timings["predicted_per_second"])
    elif completion > 0 and wall > 0:
        tok_s = completion / wall
    return {
        "wall_s": round(wall, 3),
        "completion_tokens": completion,
        "prompt_tokens": usage.get("prompt_tokens"),
        "tok_s": round(tok_s, 3) if tok_s is not None else None,
        "timings": timings if isinstance(timings, dict) else None,
        "gpu": _gpu_split(),
    }


def _bytes_per_token(model: str, gguf: Optional[Path]) -> dict[str, Any]:
    size = int(gguf.stat().st_size) if gguf and gguf.is_file() else None
    if size is None:
        return {"error": "gguf not found", "bytes_per_token": None}
    if "14B" in model:
        # Dense: approx full weight file streamed per token (lower bound-ish for MoE-less).
        bpt = float(size)
        assumption = (
            "14B dense: bytes/token ≈ GGUF file size (full weight read per token)."
        )
    else:
        # MoE: scale by active/total; note shared/attention are not separated in GGUF.
        frac = MOE_ACTIVE / MOE_TOTAL
        bpt = float(size) * frac
        assumption = (
            f"30B-A3B MoE: bytes/token ≈ file_size × ({MOE_ACTIVE}/{MOE_TOTAL}≈{frac:.4f}). "
            "This under-states shared dense/attention traffic; treat as a lower bound "
            "on bytes moved per token."
        )
    return {
        "gguf": str(gguf),
        "file_bytes": size,
        "file_gb": round(size / (1024**3), 3),
        "bytes_per_token": bpt,
        "assumption": assumption,
    }


def _effective_gbs(tok_s: float, bytes_per_token: float) -> float:
    return (tok_s * bytes_per_token) / (1024**3)


def _check_hi() -> dict[str, Any]:
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider

    provider = LemonadeProvider(model=PROD_MODEL)
    t0 = time.perf_counter()
    resp = provider.chat(
        [ChatMessage(role="user", content="Hi")],
        enable_thinking=False,
        max_tokens=32,
        timeout=120,
    )
    return {
        "wall_s": round(time.perf_counter() - t0, 3),
        "content": (resp.content or "")[:200],
        "ok": bool((resp.content or "").strip()),
    }


def _md_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Model | mean tok/s | file GB | bytes/token (assumed) | mean effective GB/s | vs 44.8 GB/s |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['mean_tok_s']} | {r['file_gb']} | "
            f"{r['bytes_per_token_gb']:.3f} GB | {r['mean_effective_gbs']} | "
            f"{r['frac_of_channel']:.0%} |"
        )
    return "\n".join(lines)


def main() -> int:
    apps = _open_apps_note()
    results: dict[str, Any] = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "production_options": {"ctx_size": int(CTX), "llamacpp_args": LLAMA_ARGS},
        "ddr5_one_channel_gbs": DDR5_ONE_CHANNEL_GBS,
        "gen_tokens": GEN_TOKENS,
        "repeats": REPEATS,
        "open_apps": apps,
        "models": {},
    }
    summary_rows: list[dict[str, Any]] = []

    for model in MODELS:
        print(f"\n=== LOAD {model} ===", flush=True)
        load = _load(model)
        print(f"load ok={load.get('ok')} {load.get('load_s')}s", flush=True)
        gguf = _find_gguf(model)
        bpt_info = _bytes_per_token(model, gguf)
        runs = []
        for i in range(REPEATS):
            print(f"  gen {i+1}/{REPEATS}…", flush=True)
            try:
                runs.append(_gen_once(model))
                print(f"    tok/s={runs[-1].get('tok_s')}", flush=True)
            except Exception as exc:
                runs.append({"error": f"{type(exc).__name__}: {exc}"})
                print(f"    ERROR {exc}", flush=True)
        tok_vals = [float(r["tok_s"]) for r in runs if r.get("tok_s")]
        mean_tok = round(sum(tok_vals) / len(tok_vals), 3) if tok_vals else None
        bpt = bpt_info.get("bytes_per_token")
        effs = []
        if mean_tok and bpt:
            for tv in tok_vals:
                effs.append(_effective_gbs(tv, float(bpt)))
        mean_eff = round(sum(effs) / len(effs), 3) if effs else None
        entry = {
            "load": load,
            "gguf": bpt_info,
            "runs": runs,
            "mean_tok_s": mean_tok,
            "mean_effective_gbs": mean_eff,
            "frac_of_one_ddr5_channel": (
                round(mean_eff / DDR5_ONE_CHANNEL_GBS, 4) if mean_eff else None
            ),
        }
        results["models"][model] = entry
        summary_rows.append(
            {
                "model": model,
                "mean_tok_s": mean_tok,
                "file_gb": bpt_info.get("file_gb"),
                "bytes_per_token_gb": (float(bpt) / (1024**3)) if bpt else 0.0,
                "mean_effective_gbs": mean_eff,
                "frac_of_channel": (
                    (mean_eff / DDR5_ONE_CHANNEL_GBS) if mean_eff else 0.0
                ),
                "assumption": bpt_info.get("assumption"),
            }
        )

    print(f"\n=== RESTORE {PROD_MODEL} ===", flush=True)
    restore = _load(PROD_MODEL)
    results["restore"] = restore
    os.environ["MINIAI_MODEL"] = PROD_MODEL
    hi = _check_hi()
    results["hi_check"] = hi
    print(f"Hi ok={hi.get('ok')} content={hi.get('content')!r}", flush=True)

    json_path = ROOT / "logs" / "round9_bandwidth.json"
    json_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    apps_names = [
        str(p.get("name") or p.get("cmdline") or "?")
        for p in (apps.get("top_processes") or [])[:8]
    ]
    paragraph = (
        f"With normal apps still open ({', '.join(apps_names)}; "
        f"free RAM {apps.get('free_ram_gb')} GB of {apps.get('total_ram_gb')} GB), "
        f"a 512-token generation was timed {REPEATS}× on each installed GGUF under "
        f"production llama.cpp options (ctx {CTX}, `{LLAMA_ARGS}`). "
        f"Effective bandwidth is tok/s × assumed bytes/token; one DDR5-5600 channel "
        f"is {DDR5_ONE_CHANNEL_GBS} GB/s. "
        + " ".join(r["assumption"] for r in summary_rows if r.get("assumption"))
        + " This note does not recommend a purchase."
    )
    md = (
        "# Round 9 — bandwidth probe\n\n"
        f"Source JSON: `{json_path.as_posix()}`\n\n"
        f"{_md_table(summary_rows)}\n\n"
        f"{paragraph}\n"
    )
    md_path = ROOT / "logs" / "round9_bandwidth.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"WROTE {md_path}")
    print(f"WROTE {json_path}")
    return 0 if hi.get("ok") and restore.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
