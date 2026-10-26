"""Measure time from send to first model token (model already loaded).

Uses a temp data root + fixture Downloads folder. Prints FIRST_TOKEN_S=<float>.
Target: < 15 s from a cold app start with Lemonade already holding the model.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
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
    # Confirm model responds quickly (already loaded)
    t_ping = time.perf_counter()
    provider.chat([ChatMessage(role="user", content="ping")], timeout=120)
    ping_s = time.perf_counter() - t_ping
    print(f"PING_S={ping_s:.3f}")

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
        "downloads": str(downloads),
        "temp_root": str(root),
        "answer_head": (answer or "")[:240],
        "ok": first_token_s is not None and first_token_s < 15.0,
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = ROOT / "logs" / f"first_token_{stamp}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"FIRST_TOKEN_S={first_token_s if first_token_s is not None else 'none'}")
    print(f"TOTAL_S={total_s:.3f}")
    print(f"JSON={path}")
    print(f"TARGET_OK={out['ok']}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
