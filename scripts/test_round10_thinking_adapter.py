"""Round 10 Part 1 — offline thinking adapter mapping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from llm.lemonade.thinking_adapter import (
    apply_model_adapter,
    sampling_for_model,
    thinking_template_kwargs,
)

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    q = thinking_template_kwargs("Qwen3.6-35B-A3B-GGUF-IQ4_XS", False)
    _check("qwen36_enable_false", q.get("enable_thinking") is False, str(q))
    n = thinking_template_kwargs("NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Q4_0", True)
    _check("nemo_enable_true", n.get("enable_thinking") is True, str(n))
    _check("nemo_truncate", n.get("truncate_history_thinking") is True, str(n))

    sq = sampling_for_model("Qwen3.6-35B-A3B-IQ4_XS", enable_thinking=True)
    _check("qwen36_think_temp", sq.get("temperature") == 1.0, str(sq))
    _check("qwen36_think_top_p", sq.get("top_p") == 0.95, str(sq))
    sqi = sampling_for_model("Qwen3.6-35B-A3B-IQ4_XS", enable_thinking=False)
    _check("qwen36_instruct_temp", sqi.get("temperature") == 0.7, str(sqi))

    sn = sampling_for_model("Nemotron-3.5-Lightning-30B", enable_thinking=False)
    _check("nemo_temp", sn.get("temperature") == 1.0, str(sn))

    sc = sampling_for_model("Qwen3-30B-A3B-GGUF", enable_thinking=False)
    _check("control_no_override", sc == {}, str(sc))

    payload = {
        "model": "Qwen3.6-35B-A3B-GGUF-IQ4_XS",
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0.1,  # caller wins
    }
    apply_model_adapter(
        payload, model="Qwen3.6-35B-A3B-GGUF-IQ4_XS", enable_thinking=False
    )
    _check("caller_temp_wins", payload.get("temperature") == 0.1, str(payload))
    _check("top_p_filled", payload.get("top_p") == 0.8, str(payload))

    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
