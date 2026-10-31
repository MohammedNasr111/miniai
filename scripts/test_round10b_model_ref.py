"""Round 10B Part 1 — per-model reference threshold for check_model_state."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if not ok:
        FAILURES += 1
    print(("PASS" if ok else "FAIL") + f" {name}" + (f" — {detail}" if detail else ""))


def test_slug_and_paths() -> None:
    from scripts import check_model_state as cms

    _check(
        "slug_safe",
        cms.model_ref_slug("Qwen36-IQ4XS-text") == "Qwen36-IQ4XS-text",
    )
    _check(
        "slug_dots",
        "Qwen3.6" in cms.model_ref_slug("Qwen3.6-35B-A3B-GGUF-IQ4_XS"),
    )
    path = cms.model_ref_path("Qwen3-30B-A3B-GGUF")
    _check("path_name", path.name == "model_ref_Qwen3-30B-A3B-GGUF.json", path.name)


def test_effective_min_from_ref(tmp_path: Path) -> None:
    from scripts import check_model_state as cms

    model = "FakeModel-RefTest"
    with patch.object(cms, "ROOT", tmp_path):
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        cms.save_model_ref(model, 13.0)
        thr, src, ref = cms.effective_tok_s_min(model)
        _check("ref_source", src == "model_ref", src)
        _check("ref_thr_90pct", abs(thr - 11.7) < 1e-9, str(thr))
        _check("ref_tok", ref is not None and float(ref["tok_s"]) == 13.0)


def test_verdict_uses_ref(tmp_path: Path) -> None:
    from scripts import check_model_state as cms

    model = "FakeModel-Verdict"
    with patch.object(cms, "ROOT", tmp_path):
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        cms.save_model_ref(model, 13.0)
        with patch.object(
            cms,
            "probe_realistic",
            return_value={
                "tok_s": 12.0,
                "tok_s_source": "predicted_per_second",
                "prompt_tokens": 100,
            },
        ):
            with patch.object(
                cms, "_llm_health", return_value={"pid": None, "model_name": model}
            ):
                with patch.object(cms, "_rss_gb", return_value=1.0):
                    with patch("agent.perf_probe.free_ram_gb", return_value=10.0):
                        with patch("agent.perf_probe.total_ram_gb", return_value=20.0):
                            with patch(
                                "scripts.probe_system._gpu_adapter_memory",
                                return_value={},
                            ):
                                ok = cms.check_model_state(
                                    write_log=False, model=model
                                )
        # 12.0 >= 11.7 → OK
        _check("ok_above_90pct", ok.get("verdict") == "OK", str(ok.get("reason")))

    with patch.object(cms, "ROOT", tmp_path):
        with patch.object(
            cms,
            "probe_realistic",
            return_value={
                "tok_s": 10.0,
                "tok_s_source": "predicted_per_second",
                "prompt_tokens": 100,
            },
        ):
            with patch.object(
                cms, "_llm_health", return_value={"pid": None, "model_name": model}
            ):
                with patch.object(cms, "_rss_gb", return_value=1.0):
                    with patch("agent.perf_probe.free_ram_gb", return_value=10.0):
                        with patch("agent.perf_probe.total_ram_gb", return_value=20.0):
                            with patch(
                                "scripts.probe_system._gpu_adapter_memory",
                                return_value={},
                            ):
                                deg = cms.check_model_state(
                                    write_log=False, model=model
                                )
        _check(
            "degraded_below_90pct",
            deg.get("verdict") == "DEGRADED",
            str(deg.get("reason")),
        )


def test_establish_ref_on_first_probe(tmp_path: Path) -> None:
    from scripts import check_model_state as cms

    model = "FakeModel-Establish"
    with patch.object(cms, "ROOT", tmp_path):
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        with patch.object(
            cms,
            "probe_realistic",
            return_value={
                "tok_s": 10.5,
                "tok_s_source": "predicted_per_second",
                "prompt_tokens": 100,
                "wall_s": 1.0,
            },
        ):
            with patch.object(
                cms, "_llm_health", return_value={"pid": None, "model_name": model}
            ):
                with patch.object(cms, "_rss_gb", return_value=1.0):
                    with patch("agent.perf_probe.free_ram_gb", return_value=10.0):
                        with patch("agent.perf_probe.total_ram_gb", return_value=20.0):
                            with patch(
                                "scripts.probe_system._gpu_adapter_memory",
                                return_value={},
                            ):
                                st = cms.check_model_state(
                                    write_log=False, model=model
                                )
        _check("establish_ok", st.get("verdict") == "OK", str(st.get("reason")))
        ref = cms.load_model_ref(model)
        _check("ref_written", ref is not None and float(ref["tok_s"]) == 10.5, str(ref))
        thr, src, _ = cms.effective_tok_s_min(model)
        _check("ref_now_source", src == "model_ref", src)
        _check("ref_thr", abs(thr - 9.45) < 1e-9, str(thr))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_slug_and_paths()
        test_effective_min_from_ref(tmp)
        test_verdict_uses_ref(tmp)
        test_establish_ref_on_first_probe(tmp)
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
