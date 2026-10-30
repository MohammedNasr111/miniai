"""Round 9: real app-path speed probe via scripts.chat session.

Cases:
  (a) 3 biggest files in a temp fixture folder
  (b) two-sentence RAM vs storage
  (c) 2-turn chat (turn 2 refers to turn 1)
  (d) optional 6-turn chat (Part 4); enable with --six-turn

Writes JSON (default logs/round9_baseline_speed.json or --out).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")


def _make_fixture() -> Path:
    downloads = Path(tempfile.mkdtemp(prefix="miniai_r9_dl_"))
    sizes = [
        ("huge.zip", 50_000_000),
        ("big.bin", 20_000_000),
        ("setup.exe", 5_000_000),
        ("notes_large.txt", 500_000),
        ("archive.dat", 200_000),
        ("photo.png", 100_000),
        ("medium.txt", 50_000),
        ("small.txt", 10_000),
        ("tiny.txt", 1_000),
        ("micro.txt", 100),
    ]
    for name, nbytes in sizes:
        p = downloads / name
        with p.open("wb") as fh:
            fh.write(b"x" * min(nbytes, 4096))
            if nbytes > 4096:
                fh.seek(nbytes - 1)
                fh.write(b"z")
    return downloads


def _parse_llm_calls(transcript_path: Path | None) -> list[dict[str, Any]]:
    if transcript_path is None or not Path(transcript_path).is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "llm_call":
            rows.append(ev)
    return rows


def _metrics_from_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    gen = 0
    prompt = 0
    cache_n = 0
    stalls: list[float] = []
    walls: list[float] = []
    toks_s: list[float] = []
    for c in calls:
        usage = c.get("usage") or {}
        gen += int(usage.get("completion_tokens") or 0)
        prompt += int(usage.get("prompt_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict) and details.get("cached_tokens") is not None:
            cache_n += int(details.get("cached_tokens") or 0)
        timings = c.get("timings") or {}
        if isinstance(timings, dict) and timings.get("cache_n") is not None:
            # Prefer per-call cache_n from timings when present.
            pass
        if c.get("stall_s") is not None:
            stalls.append(float(c["stall_s"]))
        walls.append(float(c.get("wall_clock_seconds") or 0))
        if isinstance(timings, dict) and timings.get("predicted_per_second"):
            toks_s.append(float(timings["predicted_per_second"]))
        elif isinstance(timings, dict) and timings.get("cache_n") is not None:
            cache_n = max(cache_n, int(timings.get("cache_n") or 0))
    # Use last call's timings.cache_n when available (most relevant for cache hit).
    last_cache = None
    last_prompt = None
    for c in reversed(calls):
        timings = c.get("timings") or {}
        usage = c.get("usage") or {}
        if isinstance(timings, dict) and timings.get("cache_n") is not None:
            last_cache = int(timings["cache_n"])
        if usage.get("prompt_tokens") is not None:
            last_prompt = int(usage["prompt_tokens"])
        if last_cache is not None and last_prompt is not None:
            break
    wall = sum(walls)
    mean_tok_s = sum(toks_s) / len(toks_s) if toks_s else None
    if mean_tok_s is None and gen > 0 and wall > 0:
        mean_tok_s = round(gen / wall, 3)
    return {
        "llm_calls": len(calls),
        "generated_tokens": gen,
        "prefill_tokens": prompt,
        "cache_n": last_cache if last_cache is not None else cache_n,
        "prompt_tokens_last": last_prompt,
        "cache_n_over_prompt": (
            round(last_cache / last_prompt, 4)
            if last_cache is not None and last_prompt
            else None
        ),
        "stall_s_max": max(stalls) if stalls else None,
        "stall_s_sum": round(sum(stalls), 3) if stalls else None,
        "tok_s": round(mean_tok_s, 3) if mean_tok_s is not None else None,
        "calls": [
            {
                "wall_s": c.get("wall_clock_seconds"),
                "discarded": bool(c.get("discarded")),
                "enable_thinking": c.get("enable_thinking"),
                "prompt_tokens": (c.get("usage") or {}).get("prompt_tokens"),
                "completion_tokens": (c.get("usage") or {}).get("completion_tokens"),
                "cache_n": ((c.get("timings") or {}) or {}).get("cache_n"),
                "stall_s": c.get("stall_s"),
                "free_ram_gb": c.get("free_ram_gb"),
                "lemonade_page_faults_delta": c.get("lemonade_page_faults_delta"),
                "predicted_per_second": ((c.get("timings") or {}) or {}).get(
                    "predicted_per_second"
                ),
            }
            for c in calls
        ],
    }


def _run_turn(session, prompt: str) -> dict[str, Any]:
    from agent.perf_probe import free_ram_gb, top_processes_by_rss
    from scripts.chat import run_user_turn

    first_token_s = None
    t0 = time.perf_counter()

    def on_delta(accumulated: str) -> None:
        nonlocal first_token_s
        if first_token_s is None and accumulated:
            first_token_s = time.perf_counter() - t0

    answer = run_user_turn(session, prompt, on_stream_delta=on_delta)
    wall_s = time.perf_counter() - t0
    tx_path = getattr(getattr(session, "transcript", None), "path", None)
    # Only score llm_calls after this turn's user_turn marker.
    calls_all = _parse_llm_calls(Path(tx_path) if tx_path else None)
    # Take calls since previous count stored on session.
    prev = int(getattr(session, "_r9_llm_n", 0) or 0)
    calls = calls_all[prev:]
    session._r9_llm_n = len(calls_all)  # type: ignore[attr-defined]
    metrics = _metrics_from_calls(calls)
    return {
        "prompt": prompt[:240],
        "wall_s": round(wall_s, 3),
        "first_token_s": round(first_token_s, 3) if first_token_s is not None else None,
        "answer_head": (answer or "")[:300],
        "free_ram_gb": free_ram_gb(),
        "top_processes": top_processes_by_rss(5),
        **metrics,
    }


def run_once(*, six_turn: bool = False) -> dict[str, Any]:
    from tests.support import use_temp_data

    from llm.lemonade.provider import LemonadeProvider
    from scripts.chat import end_session, new_session

    use_temp_data()
    downloads = _make_fixture()
    os.environ["MINIAI_EVAL_DOWNLOADS"] = str(downloads)

    provider = LemonadeProvider()
    session = new_session(provider)
    session._r9_llm_n = 0  # type: ignore[attr-defined]
    cases: dict[str, Any] = {}
    try:
        cases["a"] = _run_turn(
            session,
            f"What are the 3 biggest files in {downloads}? Use list_directory.",
        )
        cases["b"] = _run_turn(
            session,
            "In two sentences, what is the difference between RAM and storage?",
        )
        # Fresh session for multi-turn so turn-1 listing doesn't dominate.
        end_session(session)
        session = new_session(provider)
        session._r9_llm_n = 0  # type: ignore[attr-defined]
        t1 = _run_turn(
            session,
            "Do not use any tools. In this chat only, my codeword is ORANGE-TREE. "
            "Reply with one short sentence confirming you heard it.",
        )
        t2 = _run_turn(
            session,
            "Do not use any tools. What codeword did I just give you? "
            "Reply with only the codeword.",
        )
        cases["c"] = {"turn1": t1, "turn2": t2, "wall_s": round(t1["wall_s"] + t2["wall_s"], 3)}
        if six_turn:
            end_session(session)
            session = new_session(provider)
            session._r9_llm_n = 0  # type: ignore[attr-defined]
            turns = []
            prompts = [
                "Say the number one.",
                "Say the number two.",
                "Say the number three.",
                "Say the number four.",
                "Say the number five.",
                "What numbers have I asked you to say so far? List them.",
            ]
            for p in prompts:
                turns.append(_run_turn(session, p))
            cases["d"] = {
                "turns": turns,
                "wall_s": round(sum(t["wall_s"] for t in turns), 3),
                "cache_ratios": [
                    {
                        "i": i + 1,
                        "cache_n": t.get("cache_n"),
                        "prompt_tokens_last": t.get("prompt_tokens_last"),
                        "cache_n_over_prompt": t.get("cache_n_over_prompt"),
                    }
                    for i, t in enumerate(turns)
                ],
            }
    finally:
        try:
            end_session(session)
        except Exception:
            pass
    return {"fixture": str(downloads), "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(ROOT / "logs" / "round9_baseline_speed.json"),
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--six-turn", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if check_model_state reports DEGRADED",
    )
    args = parser.parse_args()

    from scripts.check_model_state import require_ok

    model_state = require_ok(force=bool(args.force), label="measure_real_speed")

    repeats = []
    for i in range(max(1, args.repeats)):
        print(f"\n=== measure_real_speed repeat {i+1}/{args.repeats} ===", flush=True)
        row = run_once(six_turn=bool(args.six_turn))
        repeats.append(row)
        for key, val in (row.get("cases") or {}).items():
            if isinstance(val, dict) and "wall_s" in val:
                print(f"  case {key}: wall_s={val.get('wall_s')} first={val.get('first_token_s')}", flush=True)

    out = {
        "repeats": repeats,
        "n": len(repeats),
        "six_turn": bool(args.six_turn),
        "model_state": model_state,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
