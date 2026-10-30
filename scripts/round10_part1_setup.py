"""Round 10 Part 1 — load / fit / thinking / tool probe / MTP for candidates B and C.

Usage examples:
  python scripts/round10_part1_setup.py --model Qwen3.6-35B-A3B-GGUF-IQ4_XS --letter B
  python scripts/round10_part1_setup.py --model Nemotron-3.5-Lightning-30B-A3B-Q4_0 --letter C --mtp-draft path.gguf
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = os.environ.get("LEMONADE_BASE", "http://localhost:13305/api/v1").rstrip("/")
CTX = "16384"
LLAMA_ARGS = "--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on --parallel 1"
MIN_FREE_AFTER = 2.0
OUT_DIR = ROOT / "logs"


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
    time.sleep(3)


def gpu_split() -> dict[str, Any]:
    """Dedicated / shared GPU memory split (informational)."""
    try:
        from scripts.probe_system import _gpu_adapter_memory

        return _gpu_adapter_memory()
    except Exception as exc:
        return {"error": str(exc)}


def load_model(model: str, *, llamacpp_args: str = LLAMA_ARGS) -> dict[str, Any]:
    unload()
    avail_before = _ram_avail()
    t0 = time.perf_counter()
    proc = _lemonade(
        "load",
        model,
        "--ctx-size",
        CTX,
        "--llamacpp-args",
        llamacpp_args,
        timeout=1200,
    )
    load_s = round(time.perf_counter() - t0, 2)
    out = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
    avail_after = _ram_avail()
    ok = proc.returncode == 0 and "error loading" not in out.lower()
    fit = bool(ok and avail_after >= MIN_FREE_AFTER)
    return {
        "ok": ok,
        "fit": fit,
        "load_s": load_s,
        "avail_before_gb": round(avail_before, 3),
        "avail_after_gb": round(avail_after, 3),
        "returncode": proc.returncode,
        "out_tail": out,
        "llamacpp_args": llamacpp_args,
    }


def model_state_probe() -> dict[str, Any]:
    from scripts.check_model_state import check_model_state

    return check_model_state(write_log=True)


def _tool_schema(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_PROBES: list[dict[str, Any]] = [
    {
        "id": "list_directory",
        "prompt": "List the files in C:\\Users\\Public using the list_directory tool.",
        "tools": [
            _tool_schema(
                "list_directory",
                "List directory entries",
                {"path": {"type": "string"}},
                ["path"],
            )
        ],
        "expect_name": "list_directory",
        "expect_args_keys": ["path"],
    },
    {
        "id": "read_file",
        "prompt": "Read the file C:\\Users\\Public\\readme.txt with read_file.",
        "tools": [
            _tool_schema(
                "read_file",
                "Read a text file",
                {"path": {"type": "string"}},
                ["path"],
            )
        ],
        "expect_name": "read_file",
        "expect_args_keys": ["path"],
    },
    {
        "id": "calculate",
        "prompt": "Use the calculate tool to compute 17*23.",
        "tools": [
            _tool_schema(
                "calculate",
                "Evaluate a math expression",
                {"expression": {"type": "string"}},
                ["expression"],
            )
        ],
        "expect_name": "calculate",
        "expect_args_keys": ["expression"],
    },
    {
        "id": "ws_write",
        "prompt": "Use ws_write to create workspace file probe.txt with content hello.",
        "tools": [
            _tool_schema(
                "ws_write",
                "Write a file in the workspace",
                {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                ["path", "content"],
            )
        ],
        "expect_name": "ws_write",
        "expect_args_keys": ["path", "content"],
    },
    {
        "id": "web_research",
        "prompt": "Use web_research to look up the capital of France.",
        "tools": [
            _tool_schema(
                "web_research",
                "Research a question on the web",
                {"question": {"type": "string"}},
                ["question"],
            )
        ],
        "expect_name": "web_research",
        "expect_args_keys": ["question"],
    },
]


def run_tool_probe(model: str) -> dict[str, Any]:
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider

    provider = LemonadeProvider(model=model, enable_thinking=False)
    results = []
    for spec in TOOL_PROBES:
        t0 = time.perf_counter()
        try:
            resp = provider.chat(
                [ChatMessage(role="user", content=spec["prompt"])],
                tools=spec["tools"],
                enable_thinking=False,
                timeout=180,
            )
            wall = round(time.perf_counter() - t0, 2)
            tcs = resp.tool_calls or []
            ok = False
            detail: dict[str, Any] = {"tool_calls": tcs, "content_head": (resp.content or "")[:160]}
            if tcs:
                tc0 = tcs[0]
                fn = tc0.get("function") if isinstance(tc0, dict) else None
                if not isinstance(fn, dict):
                    fn = tc0 if isinstance(tc0, dict) else {}
                name = (fn or {}).get("name") or (tc0.get("name") if isinstance(tc0, dict) else None)
                args_raw = (fn or {}).get("arguments") or "{}"
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = args_raw if isinstance(args_raw, dict) else {}
                keys_ok = all(k in args for k in spec["expect_args_keys"])
                ok = name == spec["expect_name"] and keys_ok and isinstance(args, dict)
                detail.update({"name": name, "args": args, "keys_ok": keys_ok})
            results.append({"id": spec["id"], "ok": ok, "wall_s": wall, **detail})
        except Exception as exc:
            results.append(
                {
                    "id": spec["id"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "wall_s": round(time.perf_counter() - t0, 2),
                }
            )
    passed = sum(1 for r in results if r.get("ok"))
    return {
        "passed": passed,
        "total": len(TOOL_PROBES),
        "qualified": passed == len(TOOL_PROBES),
        "results": results,
    }


def _tok_s_from_state(state: dict[str, Any]) -> Optional[float]:
    probe = state.get("probe") or {}
    if probe.get("tok_s") is not None:
        return float(probe["tok_s"])
    return None


def run_mtp_compare(model: str, draft_path: str) -> dict[str, Any]:
    """Probe ×3 with MTP off then on. Keep if ≥10% tok/s and RAM fit."""
    off_rows = []
    for i in range(3):
        load = load_model(model, llamacpp_args=LLAMA_ARGS)
        if not load.get("fit"):
            return {"skipped": True, "reason": "fit failed MTP-off load", "load": load}
        st = model_state_probe()
        off_rows.append(
            {
                "i": i + 1,
                "tok_s": _tok_s_from_state(st),
                "verdict": st.get("verdict"),
                "avail_after_gb": load.get("avail_after_gb"),
            }
        )
    # MTP on via -md draft path (llama.cpp speculative).
    draft = Path(draft_path)
    if not draft.is_file():
        return {"skipped": True, "reason": f"draft missing: {draft}", "off": off_rows}
    mtp_args = (
        f"{LLAMA_ARGS} --spec-type draft-mtp --spec-draft-n-max 2 "
        f'-md "{draft}"'
    )
    on_rows = []
    for i in range(3):
        load = load_model(model, llamacpp_args=mtp_args)
        if not load.get("fit"):
            return {
                "keep_mtp": False,
                "reason": "RAM fit failed with MTP on",
                "off": off_rows,
                "on_load": load,
            }
        st = model_state_probe()
        on_rows.append(
            {
                "i": i + 1,
                "tok_s": _tok_s_from_state(st),
                "verdict": st.get("verdict"),
                "avail_after_gb": load.get("avail_after_gb"),
                "load_ok": load.get("ok"),
            }
        )
    def mean_tok(rows: list[dict]) -> Optional[float]:
        vals = [r["tok_s"] for r in rows if r.get("tok_s") is not None]
        return (sum(vals) / len(vals)) if vals else None

    off_m, on_m = mean_tok(off_rows), mean_tok(on_rows)
    gain = None
    if off_m and on_m and off_m > 0:
        gain = (on_m - off_m) / off_m * 100.0
    keep = bool(gain is not None and gain >= 10.0)
    # Reload without MTP as default for subsequent work unless keep.
    load_model(model, llamacpp_args=LLAMA_ARGS if not keep else mtp_args)
    return {
        "keep_mtp": keep,
        "gain_pct": None if gain is None else round(gain, 2),
        "off_mean_tok_s": None if off_m is None else round(off_m, 3),
        "on_mean_tok_s": None if on_m is None else round(on_m, 3),
        "off": off_rows,
        "on": on_rows,
        "mtp_args": mtp_args,
    }


def run_one(
    *,
    letter: str,
    model: str,
    mtp_draft: Optional[str],
    skip_mtp: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "letter": letter,
        "model": model,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "ctx": int(CTX),
        "llamacpp_args": LLAMA_ARGS,
    }
    print(f"\n=== LOAD {letter} {model} ===", flush=True)
    load = load_model(model)
    row["load"] = load
    row["gpu"] = gpu_split()
    if not load.get("fit"):
        row["status"] = "skip_no_fit"
        row["reason"] = (
            f"doesn't fit at ctx {CTX}: free after load "
            f"{load.get('avail_after_gb')} < {MIN_FREE_AFTER}"
            if load.get("ok")
            else f"load failed: {load.get('out_tail', '')[-300:]}"
        )
        print(row["reason"], flush=True)
        return row
    print(f"load_s={load['load_s']} free_after={load['avail_after_gb']} GB", flush=True)
    st = model_state_probe()
    row["model_state"] = {
        "verdict": st.get("verdict"),
        "reason": st.get("reason"),
        "tok_s": _tok_s_from_state(st),
        "log_path": st.get("log_path"),
        "llm": st.get("llm"),
    }
    if st.get("verdict") != "OK":
        row["status"] = "skip_state_not_ok"
        row["reason"] = st.get("reason")
        print(f"state not OK: {st.get('reason')}", flush=True)
        return row
    print(f"thinking adapter family probe…", flush=True)
    from llm.lemonade.thinking_adapter import (
        sampling_for_model,
        thinking_template_kwargs,
    )

    row["thinking"] = {
        "template_off": thinking_template_kwargs(model, False),
        "template_on": thinking_template_kwargs(model, True),
        "sampling_off": sampling_for_model(model, enable_thinking=False),
        "sampling_on": sampling_for_model(model, enable_thinking=True),
        "notes": (
            "Both Qwen3.6 and Nemotron Lightning use "
            "chat_template_kwargs.enable_thinking; provider applies per-model sampling."
        ),
    }
    print("tool probe (5)…", flush=True)
    tools = run_tool_probe(model)
    row["tool_probe"] = tools
    print(f"tool_probe {tools['passed']}/{tools['total']}", flush=True)
    if not tools.get("qualified"):
        row["status"] = "disqualified_tools"
        row["reason"] = f"tool probe {tools['passed']}/{tools['total']}"
        return row
    if skip_mtp or not mtp_draft:
        row["mtp"] = {
            "skipped": True,
            "reason": "no draft path" if not mtp_draft else "skip_mtp flag",
        }
    else:
        print("MTP compare…", flush=True)
        row["mtp"] = run_mtp_compare(model, mtp_draft)
    row["status"] = "pass"
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--letter", required=True, choices=["B", "C"])
    parser.add_argument("--mtp-draft", default=None)
    parser.add_argument("--skip-mtp", action="store_true")
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default logs/round10_part1_<letter>.json)",
    )
    args = parser.parse_args()
    out_path = Path(args.out) if args.out else OUT_DIR / f"round10_part1_{args.letter}.json"
    row = run_one(
        letter=args.letter,
        model=args.model,
        mtp_draft=args.mtp_draft,
        skip_mtp=bool(args.skip_mtp),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {out_path} status={row.get('status')}", flush=True)
    return 0 if row.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
