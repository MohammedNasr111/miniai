"""Round 9B: detect slow Lemonade LLM decode (thermal / bad residency).

Architect correction (30 Oct): on Windows/Vulkan, high llama-server RSS mirrors
shared GPU memory and is NOT a slowness signal. Verdict is tok/s only.

OK when tok/s ≥ 11 on a realistic ~6k-token probe (system_prompt + tools +
short user, generate 128 tokens). RSS and GPU memory are logged only.
Writes logs/model_state_<stamp>.json. Exit 0=OK, 1=DEGRADED, 2=error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOK_S_MIN = 11.0
PROBE_TOKENS = 128
PROBE_USER = "In one short paragraph, what is a page fault?"


def _llm_health() -> dict[str, Any]:
    import requests
    from config import settings

    base = settings.LEMONADE_BASE_URL.rstrip("/")
    r = requests.get(f"{base}/health", timeout=5)
    r.raise_for_status()
    data = r.json() if r.content else {}
    for m in data.get("all_models_loaded") or []:
        if not isinstance(m, dict):
            continue
        if str(m.get("type") or "").lower() != "llm":
            continue
        loaded = bool(m.get("loaded")) or str(m.get("status") or "").lower() == "ready"
        if not loaded:
            continue
        return {
            "model_name": m.get("model_name"),
            "pid": m.get("pid"),
            "device": m.get("device"),
            "checkpoint": m.get("checkpoint"),
            "recipe_options": m.get("recipe_options"),
            "launch_command": m.get("launch_command"),
            "status": m.get("status"),
        }
    from agent.perf_probe import _lemonade_llm_pid

    pid = _lemonade_llm_pid()
    if pid is not None:
        return {
            "model_name": data.get("model_loaded") or settings.LEMONADE_MODEL,
            "pid": pid,
            "device": None,
            "fallback": "process_scan",
        }
    return {"error": "no loaded llm", "raw_keys": list(data.keys()), "health": data}


def _rss_gb(pid: Optional[int]) -> Optional[float]:
    try:
        import psutil
    except Exception:
        return None
    if pid is not None:
        try:
            return round(psutil.Process(int(pid)).memory_info().rss / (1024**3), 3)
        except Exception:
            pass
    best = None
    try:
        for proc in psutil.process_iter(["pid", "name", "memory_info", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "llama-server" not in name:
                    continue
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                if "embed" in cmd:
                    continue
                mi = proc.info.get("memory_info")
                rss = int(getattr(mi, "rss", 0) or 0)
                gb = rss / (1024**3)
                if best is None or gb > best:
                    best = gb
            except (psutil.Error, TypeError, ValueError):
                continue
    except Exception:
        return None
    return round(best, 3) if best is not None else None


def _realistic_messages() -> list[dict[str, str]]:
    """Same fixed prefix a real turn uses (~6k tokens with tools)."""
    from scripts.agent_loop import system_prompt

    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": PROBE_USER},
    ]


def _realistic_tools() -> list:
    from tools.registry import active_tool_schemas

    return active_tool_schemas()


def probe_realistic(model: Optional[str] = None) -> dict[str, Any]:
    """One 128-token generation on system+tools+short user; return tok/s etc."""
    import requests
    from config import settings

    name = model or settings.LEMONADE_MODEL
    messages = _realistic_messages()
    tools = _realistic_tools()
    url = f"{settings.LEMONADE_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": name,
        "messages": messages,
        "tools": tools,
        "max_tokens": PROBE_TOKENS,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    # Rough prompt size estimate (chars/3.5), tools included.
    from agent.context_budget import estimate_tokens

    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    try:
        tools_chars = len(json.dumps(tools, ensure_ascii=False))
    except (TypeError, ValueError):
        tools_chars = 0
    est_prompt_tokens = round(estimate_tokens("x" * (prompt_chars + tools_chars)))

    t0 = time.perf_counter()
    r = requests.post(url, json=payload, timeout=600)
    wall = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    usage = data.get("usage") or {}
    timings = data.get("timings") or {}
    completion = int(usage.get("completion_tokens") or 0)
    prompt_tokens = usage.get("prompt_tokens")
    # Round 9E: verdict tok/s must be llama.cpp decode rate only — never wall-clock
    # (wall includes prefill/queue and falsely flags "Running slowly" after launch).
    tok_s = None
    tok_s_source = None
    if isinstance(timings, dict) and timings.get("predicted_per_second"):
        tok_s = float(timings["predicted_per_second"])
        tok_s_source = "predicted_per_second"
    return {
        "wall_s": round(wall, 3),
        "completion_tokens": completion,
        "prompt_tokens": prompt_tokens,
        "est_prompt_tokens": est_prompt_tokens,
        "tok_s": round(tok_s, 3) if tok_s is not None else None,
        "tok_s_source": tok_s_source,
        "timings": timings if isinstance(timings, dict) else None,
        "model": name,
        "probe_kind": "realistic_system_tools",
        "user": PROBE_USER,
    }


def check_model_state(
    *,
    write_log: bool = True,
    skip_probe: bool = False,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Return state dict with verdict OK|DEGRADED|ERROR.

    Verdict uses tok/s only (≥ TOK_S_MIN). RSS/GPU are informational.
    """
    from agent.perf_probe import free_ram_gb, total_ram_gb
    from scripts.probe_system import _gpu_adapter_memory

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stamp": stamp,
        "thresholds": {
            "tok_s_min": TOK_S_MIN,
            "note": "RSS logged only; not used in verdict (architect 30 Oct)",
        },
    }
    try:
        llm = _llm_health()
        out["llm"] = llm
        pid = llm.get("pid")
        rss = _rss_gb(int(pid) if pid is not None else None)
        out["llm_rss_gb"] = rss
        out["free_ram_gb"] = free_ram_gb()
        out["total_ram_gb"] = total_ram_gb()
        out["gpu"] = _gpu_adapter_memory()
        if skip_probe:
            out["probe"] = {"skipped": True}
            out["verdict"] = "OK"
            out["reason"] = "probe skipped (informational RSS/GPU only)"
        else:
            probe = probe_realistic(model=model or llm.get("model_name"))
            out["probe"] = probe
            tok_s = probe.get("tok_s")
            if tok_s is None or probe.get("tok_s_source") != "predicted_per_second":
                # Missing timings → do not call the model "slow" (would false-chip).
                out["verdict"] = "UNKNOWN"
                out["reason"] = "predicted_per_second unavailable (no wall-clock fallback)"
            elif float(tok_s) < TOK_S_MIN:
                out["verdict"] = "DEGRADED"
                out["reason"] = f"tok/s {tok_s} < {TOK_S_MIN}"
            else:
                out["verdict"] = "OK"
                out["reason"] = (
                    f"tok/s={tok_s} ≥ {TOK_S_MIN} "
                    f"(RSS={rss} GB logged only; "
                    f"prompt_tokens={probe.get('prompt_tokens') or probe.get('est_prompt_tokens')})"
                )
    except Exception as exc:
        out["verdict"] = "ERROR"
        out["reason"] = f"{type(exc).__name__}: {exc}"

    if write_log:
        path = ROOT / "logs" / f"model_state_{stamp}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        out["log_path"] = str(path)
    return out


def require_ok(*, force: bool = False, label: str = "measure") -> dict[str, Any]:
    """Run check; raise SystemExit(2) if DEGRADED/ERROR unless force."""
    state = check_model_state(write_log=True)
    print(
        f"[model_state] {state.get('verdict')}: {state.get('reason')} "
        f"(rss={state.get('llm_rss_gb')} tok/s="
        f"{(state.get('probe') or {}).get('tok_s')} "
        f"free_ram={state.get('free_ram_gb')} "
        f"log={state.get('log_path')})",
        flush=True,
    )
    if state.get("verdict") == "OK" or force:
        if force and state.get("verdict") != "OK":
            print(
                f"[model_state] --force: continuing {label} despite "
                f"{state.get('verdict')}",
                flush=True,
            )
        return state
    print(
        f"[model_state] refusing to {label}: {state.get('reason')}. "
        "Run scripts/restore_model.py, or pass --force to override.",
        flush=True,
    )
    raise SystemExit(2)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check Lemonade LLM decode speed")
    parser.add_argument("--skip-probe", action="store_true")
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    state = check_model_state(
        write_log=True, skip_probe=bool(args.skip_probe), model=args.model
    )
    print(json.dumps(state, indent=2))
    print(f"VERDICT={state.get('verdict')}")
    if state.get("log_path"):
        print(f"LOG={state['log_path']}")
    if state.get("verdict") == "OK":
        return 0
    if state.get("verdict") == "DEGRADED":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
