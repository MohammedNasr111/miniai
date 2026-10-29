"""Round 9 Part 0: snapshot Lemonade, RAM, GPU counters, top processes.

Writes logs/round9_system.json. No elevation. Never prints secrets.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "logs" / "round9_system.json"


def _run_cmd(args: list[str], timeout: int = 60) -> dict[str, Any]:
    from config.proc import hidden_subprocess_kwargs

    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        return {
            "argv": args,
            "returncode": cp.returncode,
            "stdout": (cp.stdout or "")[-8000:],
            "stderr": (cp.stderr or "")[-2000:],
        }
    except Exception as exc:
        return {"argv": args, "error": f"{type(exc).__name__}: {exc}"}


def _lemonade_version() -> str:
    r = _run_cmd(["lemonade", "--version"], timeout=30)
    text = (r.get("stdout") or "").strip() or (r.get("stderr") or "").strip()
    return text or str(r.get("error") or "unknown")


def _http_get(path: str, timeout: float = 5.0) -> Any:
    import requests
    from config import settings

    base = settings.LEMONADE_BASE_URL.rstrip("/")
    r = requests.get(f"{base}{path}", timeout=timeout)
    r.raise_for_status()
    if not r.content:
        return None
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:2000]}


def _loaded_model_and_options() -> dict[str, Any]:
    out: dict[str, Any] = {"health": None, "export": None}
    try:
        out["health"] = _http_get("/health")
    except Exception as exc:
        out["health_error"] = f"{type(exc).__name__}: {exc}"
    model = None
    health = out.get("health") or {}
    if isinstance(health, dict):
        model = health.get("model_loaded")
        for m in health.get("all_models_loaded") or []:
            if str(m.get("type") or "").lower() == "llm":
                model = m.get("model_name") or model
                out["llm"] = {
                    "model_name": m.get("model_name"),
                    "checkpoint": m.get("checkpoint"),
                    "device": m.get("device"),
                    "recipe": m.get("recipe"),
                    "recipe_options": m.get("recipe_options"),
                    "max_context_window": m.get("max_context_window"),
                    "pid": m.get("pid"),
                    "launch_command": m.get("launch_command"),
                }
                break
    if model:
        # lemonade export <model> — best-effort; may be unsupported.
        out["export"] = _run_cmd(["lemonade", "export", str(model)], timeout=90)
    return out


def _stats() -> Any:
    try:
        return _http_get("/stats")
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _gpu_adapter_memory() -> dict[str, Any]:
    """GPU dedicated/shared usage via Get-Counter (no elevation)."""
    from config.proc import hidden_subprocess_kwargs

    ps = (
        "$ErrorActionPreference='Stop'; "
        "$c = Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage',"
        "'\\GPU Adapter Memory(*)\\Shared Usage'; "
        "$rows = @(); "
        "foreach ($s in $c.CounterSamples) { "
        "  $rows += [pscustomobject]@{ Path=$s.Path; Instance=$s.InstanceName; "
        "    Value=[double]$s.CookedValue } "
        "}; "
        "$rows | ConvertTo-Json -Compress"
    )
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=45,
            encoding="utf-8",
            errors="replace",
            **hidden_subprocess_kwargs(),
        )
        text = (cp.stdout or "").strip()
        if cp.returncode != 0 or not text:
            return {
                "error": (cp.stderr or text or f"rc={cp.returncode}")[:500],
                "returncode": cp.returncode,
            }
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        dedicated = []
        shared = []
        for row in data or []:
            path = str(row.get("Path") or "").lower()
            val = float(row.get("Value") or 0.0)
            entry = {
                "instance": row.get("Instance"),
                "bytes": val,
                "gb": round(val / (1024**3), 3),
            }
            if "dedicated" in path:
                dedicated.append(entry)
            elif "shared" in path:
                shared.append(entry)
        return {"dedicated": dedicated, "shared": shared}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    from agent.perf_probe import free_ram_gb, top_processes_by_rss, total_ram_gb

    payload = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lemonade_version": _lemonade_version(),
        "loaded_model": _loaded_model_and_options(),
        "stats": _stats(),
        "gpu_adapter_memory": _gpu_adapter_memory(),
        "ram": {
            "total_gb": total_ram_gb(),
            "free_gb": free_ram_gb(),
        },
        "top_processes_rss": top_processes_by_rss(10),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {OUT}")
    print("lemonade", payload["lemonade_version"])
    print("ram", payload["ram"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
