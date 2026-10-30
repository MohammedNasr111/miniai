"""Measure time from send to first model token.

Modes:
  default / --no-warmup: ping only (weights hot), then first real turn.
  --warmup: send the same system+tools+"." warm-up the app uses, then measure.

Restart the app between comparative runs; do not unload models in ways the
app cannot recover from. Writes logs/first_token_<stamp>.json (and optional
--out).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _run_app_warmup(provider) -> float:
    """Same request as WebviewBridge.start_model_warmup (no transcript)."""
    from llm.base import ChatMessage
    from scripts.agent_loop import system_prompt
    from tools.registry import active_tool_schemas

    t0 = time.perf_counter()
    provider.chat(
        [
            ChatMessage(role="system", content=system_prompt()),
            ChatMessage(role="user", content="."),
        ],
        tools=active_tool_schemas(),
        enable_thinking=False,
        max_tokens=1,
        timeout=300,
    )
    return time.perf_counter() - t0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Run app-path system+tools warm-up before measuring first token",
    )
    parser.add_argument("--no-warmup", action="store_true", help="Explicit cold-prefix measure")
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if check_model_state reports DEGRADED",
    )
    args = parser.parse_args()
    do_warmup = bool(args.warmup) and not bool(args.no_warmup)

    from scripts.check_model_state import require_ok

    model_state = require_ok(force=bool(args.force), label="measure_first_token")

    from tests.support import use_temp_data

    root = use_temp_data()
    # Fixture "Downloads"
    downloads = Path(tempfile.mkdtemp(prefix="miniai_dl_"))
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
        # Sparse-ish: write head + seek for large files
        with p.open("wb") as fh:
            fh.write(b"x" * min(nbytes, 4096))
            if nbytes > 4096:
                fh.seek(nbytes - 1)
                fh.write(b"z")

    # Point system prompt / tools at fixture by env the agent understands
    os.environ["MINIAI_EVAL_DOWNLOADS"] = str(downloads)

    from llm.lemonade.provider import LemonadeProvider
    from llm.base import ChatMessage
    from scripts.chat import new_session, run_user_turn

    provider = LemonadeProvider()
    # Confirm weights respond (already loaded in Lemonade).
    t_ping = time.perf_counter()
    provider.chat([ChatMessage(role="user", content="ping")], timeout=120)
    ping_s = time.perf_counter() - t_ping
    print(f"PING_S={ping_s:.3f}")

    warmup_s = None
    if do_warmup:
        warmup_s = _run_app_warmup(provider)
        print(f"WARMUP_S={warmup_s:.3f}")

    session = new_session(provider)
    first_token_s = None
    t0 = None

    def on_delta(accumulated: str) -> None:
        nonlocal first_token_s
        if first_token_s is None and accumulated:
            first_token_s = time.perf_counter() - t0

    question = (
        f"What are the 5 biggest files in my Downloads folder? "
        f"Use list_directory on this exact path: {downloads}"
    )
    t0 = time.perf_counter()
    answer = run_user_turn(
        session,
        question,
        on_stream_delta=on_delta,
    )
    total_s = time.perf_counter() - t0
    out = {
        "first_token_s": first_token_s,
        "total_s": total_s,
        "ping_s": ping_s,
        "warmup": do_warmup,
        "warmup_s": warmup_s,
        "downloads": str(downloads),
        "temp_root": str(root),
        "answer_head": (answer or "")[:240],
        "ok": first_token_s is not None and first_token_s < 15.0,
        "model_state": model_state,
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(args.out) if args.out else ROOT / "logs" / f"first_token_{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"FIRST_TOKEN_S={first_token_s if first_token_s is not None else 'none'}")
    print(f"TOTAL_S={total_s:.3f}")
    print(f"JSON={path}")
    print(f"WARMUP={do_warmup}")
    print(f"TARGET_OK={out['ok']}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
