"""Round 9E Part 3 — speed chip uses predicted_per_second; two DEGRADED to show."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" — {detail}" if detail else ""))


def test_probe_ignores_wall_clock() -> None:
    from scripts import check_model_state as cms

    fake = {
        "usage": {"completion_tokens": 128, "prompt_tokens": 100},
        "timings": {},  # no predicted_per_second
    }

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return fake

    with patch.object(cms, "_realistic_messages", return_value=[{"role": "user", "content": "x"}]):
        with patch.object(cms, "_realistic_tools", return_value=[]):
            with patch("requests.post", return_value=_Resp()):
                probe = cms.probe_realistic(model="fake")
    _check("no_pps_tok_s_none", probe.get("tok_s") is None, str(probe.get("tok_s")))
    _check("no_pps_source_none", probe.get("tok_s_source") is None)

    fake["timings"] = {"predicted_per_second": 13.5}
    with patch.object(cms, "_realistic_messages", return_value=[{"role": "user", "content": "x"}]):
        with patch.object(cms, "_realistic_tools", return_value=[]):
            with patch("requests.post", return_value=_Resp()):
                probe2 = cms.probe_realistic(model="fake")
    _check("with_pps_tok_s", probe2.get("tok_s") == 13.5, str(probe2.get("tok_s")))
    _check(
        "with_pps_source",
        probe2.get("tok_s_source") == "predicted_per_second",
    )


def test_verdict_unknown_without_pps() -> None:
    from scripts import check_model_state as cms

    with patch.object(
        cms,
        "probe_realistic",
        return_value={"tok_s": None, "tok_s_source": None, "prompt_tokens": 1},
    ):
        with patch.object(cms, "_llm_health", return_value={"pid": None, "model_name": "x"}):
            with patch.object(cms, "_rss_gb", return_value=1.0):
                with patch("agent.perf_probe.free_ram_gb", return_value=10.0):
                    with patch("agent.perf_probe.total_ram_gb", return_value=20.0):
                        with patch("scripts.probe_system._gpu_adapter_memory", return_value={}):
                            st = cms.check_model_state(write_log=False)
    _check("verdict_unknown", st.get("verdict") == "UNKNOWN", str(st.get("verdict")))


def test_slow_chip_needs_two_degraded() -> None:
    from app.webview_approver import AppBridge

    ap = AppBridge.__new__(AppBridge)
    ap._perf_degraded_streak = 0
    ap._restore_busy = False
    ap._perf_verdict = "OK"
    ap._perf_free_ram_gb = 10.0

    def _chip() -> bool:
        return ap._perf_degraded_streak >= 2 and not ap._restore_busy

    _check("chip_off_init", not _chip())
    ap._perf_verdict = "DEGRADED"
    ap._perf_degraded_streak = 1
    _check("chip_off_one", not _chip())
    ap._perf_degraded_streak = 2
    _check("chip_on_two", _chip())
    ap._perf_degraded_streak = 0
    _check("chip_clears", not _chip())


def test_refresh_writing_speed_from_transcript(tmp_path: Path | None = None) -> None:
    from app.webview_approver import AppBridge

    root = Path(tmp_path) if tmp_path else ROOT / "logs"
    root.mkdir(parents=True, exist_ok=True)
    tx = root / "_r9e_speed_chip_tx.jsonl"
    rows = [
        {
            "type": "llm_call",
            "discarded": True,
            "timings": {"predicted_per_second": 99.0},
        },
        {
            "type": "llm_call",
            "discarded": False,
            "timings": {"predicted_per_second": 12.4},
        },
    ]
    tx.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    ap = AppBridge.__new__(AppBridge)
    ap._last_tok_s = 0.0
    session = MagicMock()
    session.transcript = MagicMock()
    session.transcript.path = str(tx)
    ap._session = session
    ap._refresh_writing_speed(cloud=False)
    _check("local_pps", abs(ap._last_tok_s - 12.4) < 0.01, str(ap._last_tok_s))
    ap._refresh_writing_speed(cloud=True)
    _check("cloud_dash", ap._last_tok_s == 0.0, str(ap._last_tok_s))


def main() -> int:
    test_probe_ignores_wall_clock()
    test_verdict_unknown_without_pps()
    test_slow_chip_needs_two_degraded()
    test_refresh_writing_speed_from_transcript()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
