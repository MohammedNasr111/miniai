"""Round 9B Part 1b: 12-min sustained generation, 10-min idle, 3 recovery probes.

Writes logs/round9b_thermal.json. Read-only powercfg. No admin.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUSTAIN_S = 12 * 60
IDLE_S = 10 * 60
RECOVERY_N = 3


def _power_plan() -> dict[str, Any]:
    from config.proc import hidden_subprocess_kwargs

    try:
        cp = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        return {
            "returncode": cp.returncode,
            "stdout": (cp.stdout or "").strip(),
            "stderr": (cp.stderr or "").strip()[:500],
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    from agent.perf_probe import free_ram_gb
    from scripts.check_model_state import check_model_state, probe_realistic

    state0 = check_model_state(write_log=True)
    if state0.get("verdict") != "OK":
        print(
            f"Refusing thermal test: model_state={state0.get('verdict')} "
            f"{state0.get('reason')}. Restore first.",
            flush=True,
        )
        return 2

    out: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "power_plan": _power_plan(),
        "model_state_before": state0,
        "sustain_s": SUSTAIN_S,
        "idle_s": IDLE_S,
        "calls": [],
        "recovery": [],
    }

    print(f"[thermal] sustained load for {SUSTAIN_S}s…", flush=True)
    t_start = time.perf_counter()
    n = 0
    while time.perf_counter() - t_start < SUSTAIN_S:
        n += 1
        elapsed = time.perf_counter() - t_start
        try:
            probe = probe_realistic()
            row = {
                "i": n,
                "elapsed_s": round(elapsed, 1),
                "minute": round(elapsed / 60.0, 2),
                "tok_s": probe.get("tok_s"),
                "wall_s": probe.get("wall_s"),
                "prompt_tokens": probe.get("prompt_tokens"),
                "completion_tokens": probe.get("completion_tokens"),
                "free_ram_gb": free_ram_gb(),
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        except Exception as exc:
            row = {
                "i": n,
                "elapsed_s": round(elapsed, 1),
                "minute": round(elapsed / 60.0, 2),
                "error": f"{type(exc).__name__}: {exc}",
                "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        out["calls"].append(row)
        print(
            f"  [{row.get('minute')} min] tok/s={row.get('tok_s')} "
            f"wall={row.get('wall_s')} {row.get('error') or ''}",
            flush=True,
        )
        # Persist incrementally so a crash still leaves evidence.
        path = ROOT / "logs" / "round9b_thermal.json"
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    tok_vals = [float(c["tok_s"]) for c in out["calls"] if c.get("tok_s")]
    first_tok = tok_vals[0] if tok_vals else None
    last_tok = tok_vals[-1] if tok_vals else None
    drop_pct = None
    if first_tok and last_tok and first_tok > 0:
        drop_pct = round(100.0 * (first_tok - last_tok) / first_tok, 1)
    out["sustain_summary"] = {
        "n_calls": len(out["calls"]),
        "first_tok_s": first_tok,
        "last_tok_s": last_tok,
        "min_tok_s": min(tok_vals) if tok_vals else None,
        "max_tok_s": max(tok_vals) if tok_vals else None,
        "drop_pct_first_to_last": drop_pct,
    }
    print(f"[thermal] sustain done: {out['sustain_summary']}", flush=True)

    print(f"[thermal] idle {IDLE_S}s…", flush=True)
    idle_t0 = time.perf_counter()
    while time.perf_counter() - idle_t0 < IDLE_S:
        left = IDLE_S - (time.perf_counter() - idle_t0)
        time.sleep(min(30.0, max(1.0, left)))
        print(f"  idle… {int(left)}s left", flush=True)

    print(f"[thermal] recovery probes ×{RECOVERY_N}…", flush=True)
    for i in range(RECOVERY_N):
        probe = probe_realistic()
        row = {
            "i": i + 1,
            "tok_s": probe.get("tok_s"),
            "wall_s": probe.get("wall_s"),
            "prompt_tokens": probe.get("prompt_tokens"),
            "free_ram_gb": free_ram_gb(),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        out["recovery"].append(row)
        print(f"  recovery {i+1}: tok/s={row.get('tok_s')}", flush=True)

    rec_vals = [float(r["tok_s"]) for r in out["recovery"] if r.get("tok_s")]
    mean_rec = round(sum(rec_vals) / len(rec_vals), 3) if rec_vals else None
    thermal = False
    if drop_pct is not None and drop_pct >= 25.0:
        if mean_rec is not None and first_tok and mean_rec >= first_tok * 0.9:
            thermal = True
            reading = (
                f"tok/s fell {drop_pct}% over 12 min and recovered after idle "
                f"(mean recovery {mean_rec}) → thermal"
            )
        else:
            reading = (
                f"tok/s fell {drop_pct}% over 12 min; recovery mean={mean_rec} "
                f"(did not clearly recover) → possible thermal or sticky throttle"
            )
    else:
        reading = (
            f"tok/s did not fall ≥25% over 12 min "
            f"(drop={drop_pct}%). Slowness has another cause; not thermal by this test."
        )
    out["reading"] = reading
    out["thermal_by_rule"] = thermal
    out["model_state_after"] = check_model_state(write_log=True)

    path = ROOT / "logs" / "round9b_thermal.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"READING={reading}", flush=True)
    print(f"WROTE {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
