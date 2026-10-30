"""Round 9B: unload LLM, wait for free RAM, reload production 30B-A3B.

Does not kill user processes. Embedding model may stay loaded.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROD_MODEL = "Qwen3-30B-A3B-GGUF"
CTX = "16384"
LLAMA_ARGS = "--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on --parallel 1"
FREE_RAM_TARGET_GB = 8.0
WAIT_MAX_S = 120


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


def _unload_llm(model: str = PROD_MODEL) -> dict[str, Any]:
    # LLM only — do not unload --all (keep embeddings).
    proc = _lemonade("unload", model, timeout=180)
    out = (proc.stdout or "") + (proc.stderr or "")
    time.sleep(2)
    return {
        "returncode": proc.returncode,
        "out_tail": out[-600:],
    }


def _wait_free_ram(
    target_gb: float = FREE_RAM_TARGET_GB, max_s: float = WAIT_MAX_S
) -> dict[str, Any]:
    from agent.perf_probe import free_ram_gb

    t0 = time.perf_counter()
    samples: list[dict[str, Any]] = []
    while True:
        free = free_ram_gb()
        elapsed = round(time.perf_counter() - t0, 1)
        samples.append({"elapsed_s": elapsed, "free_ram_gb": free})
        print(f"[restore] free_ram_gb={free} (target ≥ {target_gb})", flush=True)
        if free is not None and float(free) >= target_gb:
            return {
                "ok": True,
                "free_ram_gb": free,
                "waited_s": elapsed,
                "samples": samples,
            }
        if elapsed >= max_s:
            return {
                "ok": False,
                "free_ram_gb": free,
                "waited_s": elapsed,
                "samples": samples,
                "note": (
                    f"Free RAM still under {target_gb} GB after {max_s}s. "
                    "Close heavy apps if restore stays DEGRADED — "
                    "this script will not kill user processes."
                ),
            }
        time.sleep(10)


def _load_prod(model: str = PROD_MODEL) -> dict[str, Any]:
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
        "model": model,
        "ctx_size": int(CTX),
        "llamacpp_args": LLAMA_ARGS,
    }


def restore_model(
    *,
    retries: int = 1,
    on_progress: Optional[Any] = None,
) -> dict[str, Any]:
    from scripts.check_model_state import check_model_state

    def _progress(msg: str) -> None:
        print(f"[restore] {msg}", flush=True)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    result: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "before": None,
        "unload": None,
        "wait_ram": None,
        "load": None,
        "after_attempts": [],
        "final_verdict": None,
    }
    try:
        result["before"] = check_model_state(write_log=True)
    except Exception as exc:
        result["before"] = {"error": f"{type(exc).__name__}: {exc}"}

    _progress("Unloading LLM…")
    result["unload"] = _unload_llm(PROD_MODEL)
    _progress("Waiting for free RAM…")
    result["wait_ram"] = _wait_free_ram()
    if not result["wait_ram"].get("ok"):
        note = result["wait_ram"].get("note") or ""
        _progress(str(note))
        print(note, flush=True)

    attempt = 0
    while attempt <= retries:
        attempt += 1
        _progress(f"Loading {PROD_MODEL} (attempt {attempt})…")
        load = _load_prod(PROD_MODEL)
        result["load"] = load
        _progress(f"Load finished ok={load.get('ok')} in {load.get('load_s')}s")
        time.sleep(2)
        state = check_model_state(write_log=True)
        result["after_attempts"].append(state)
        _progress(f"State={state.get('verdict')} {state.get('reason')}")
        if state.get("verdict") == "OK":
            result["final_verdict"] = "OK"
            break
        if attempt <= retries:
            _progress("Still DEGRADED — unload and retry once…")
            _unload_llm(PROD_MODEL)
            result["wait_ram_retry"] = _wait_free_ram()
        else:
            result["final_verdict"] = state.get("verdict") or "DEGRADED"
            result["stop"] = (
                "Still DEGRADED after retry. Close heavy apps or reboot, "
                "then re-run scripts/restore_model.py. "
                "This script does not kill user processes."
            )

    path = ROOT / "logs" / "round9b_restore.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    result["log_path"] = str(path)
    print(f"WROTE {path}", flush=True)
    print(f"FINAL_VERDICT={result.get('final_verdict')}", flush=True)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    result = restore_model(retries=1)
    if result.get("final_verdict") == "OK":
        return 0
    print(result.get("stop") or "restore failed", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
