"""Per-call RAM / Lemonade page-fault probes for llm_call instrumentation."""

from __future__ import annotations

from typing import Any, Optional

_last_page_faults: Optional[int] = None


def free_ram_gb() -> Optional[float]:
    try:
        import psutil

        return round(float(psutil.virtual_memory().available) / (1024**3), 3)
    except Exception:
        return None


def total_ram_gb() -> Optional[float]:
    try:
        import psutil

        return round(float(psutil.virtual_memory().total) / (1024**3), 3)
    except Exception:
        return None


def top_processes_by_rss(n: int = 10) -> list[dict[str, Any]]:
    try:
        import psutil
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            info = proc.info
            mi = info.get("memory_info")
            rss = int(getattr(mi, "rss", 0) or 0)
            rows.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name") or "",
                    "rss_gb": round(rss / (1024**3), 3),
                }
            )
        except (psutil.Error, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: float(r.get("rss_gb") or 0), reverse=True)
    return rows[:n]


def _lemonade_llm_pid() -> Optional[int]:
    """Prefer Lemonade health API's loaded LLM pid; fall back to process scan."""
    try:
        import requests
        from config import settings

        base = settings.LEMONADE_BASE_URL.rstrip("/")
        r = requests.get(f"{base}/health", timeout=2)
        if r.ok:
            data = r.json() if r.content else {}
            for m in data.get("all_models_loaded") or []:
                if str(m.get("type") or "").lower() == "llm" and m.get("pid"):
                    return int(m["pid"])
            # Older shape: model_loaded name only — scan children below.
    except Exception:
        pass
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if "llama-server" in name or "lemonade" in name:
                    cmd = " ".join(proc.info.get("cmdline") or []).lower()
                    if "embed" in cmd:
                        continue
                    return int(proc.info["pid"])
            except (psutil.Error, TypeError, ValueError):
                continue
    except Exception:
        pass
    return None


def lemonade_page_faults() -> Optional[int]:
    """Current num_page_faults for the Lemonade LLM process, or None."""
    try:
        import psutil

        pid = _lemonade_llm_pid()
        if pid is None:
            return None
        mi = psutil.Process(pid).memory_info()
        faults = getattr(mi, "num_page_faults", None)
        if faults is None:
            return None
        return int(faults)
    except Exception:
        return None


def lemonade_page_faults_delta() -> Optional[int]:
    """Delta since the previous probe (None on first call or if unavailable)."""
    global _last_page_faults
    cur = lemonade_page_faults()
    if cur is None:
        return None
    prev = _last_page_faults
    _last_page_faults = cur
    if prev is None:
        return None
    return max(0, cur - prev)


def stall_s(
    wall_clock_seconds: float,
    timings: Optional[dict[str, Any]],
) -> Optional[float]:
    """wall − (prompt_ms + predicted_ms)/1000 when timings exist."""
    if not timings or not isinstance(timings, dict):
        return None
    try:
        prompt_ms = float(timings.get("prompt_ms") or 0.0)
        predicted_ms = float(timings.get("predicted_ms") or 0.0)
        if prompt_ms <= 0 and predicted_ms <= 0:
            return None
        model_s = (prompt_ms + predicted_ms) / 1000.0
        return round(max(0.0, float(wall_clock_seconds) - model_s), 3)
    except (TypeError, ValueError):
        return None


def snapshot_before_call() -> dict[str, Any]:
    """Capture probes at the start of an llm call (free RAM + fault baseline)."""
    return {
        "free_ram_gb_before": free_ram_gb(),
        "page_faults_before": lemonade_page_faults(),
    }


def enrich_llm_fields(
    *,
    wall_clock_seconds: float,
    timings: Optional[dict[str, Any]],
    before: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Fields to merge into an llm_call transcript event."""
    before = before or {}
    faults_before = before.get("page_faults_before")
    faults_after = lemonade_page_faults()
    delta: Optional[int] = None
    if faults_before is not None and faults_after is not None:
        try:
            delta = max(0, int(faults_after) - int(faults_before))
        except (TypeError, ValueError):
            delta = None
    # Keep module baseline in sync for callers that use the delta helper.
    global _last_page_faults
    if faults_after is not None:
        _last_page_faults = int(faults_after)

    out: dict[str, Any] = {
        "free_ram_gb": {
            "before": before.get("free_ram_gb_before"),
            "after": free_ram_gb(),
        },
        "lemonade_page_faults_delta": delta,
        "stall_s": stall_s(wall_clock_seconds, timings),
    }
    return out
