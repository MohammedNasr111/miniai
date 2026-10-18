"""Local speed / cache / alternative-model measurements (no default changes).

Writes JSON results under logs/. Safe to re-run; does not --save-options.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "logs" / f"local_speed_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

USABLE_RAM_GB = 23.62
RAM_LIMIT_GB = 21.0


def _ram_gb() -> dict:
    # Prefer GlobalMemoryStatusEx via ctypes.
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total = stat.ullTotalPhys / (1024**3)
    avail = stat.ullAvailPhys / (1024**3)
    used = total - avail
    return {
        "total_gb": round(total, 3),
        "avail_gb": round(avail, 3),
        "used_gb": round(used, 3),
        "used_over_23_62": round(used / USABLE_RAM_GB, 4),
    }


def _lemonade(*args: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["lemonade", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def measure_schema_cost() -> dict:
    from config import settings
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider
    from tools.registry import TOOL_SCHEMAS

    provider = LemonadeProvider()
    messages = [ChatMessage(role="user", content="Reply with the word OK.")]
    out: dict = {"question": "Reply with the word OK."}
    for label, tools in (("with_tools", TOOL_SCHEMAS), ("no_tools", None)):
        started = time.perf_counter()
        resp = provider.chat(
            messages,
            tools=tools,
            enable_thinking=False,
            timeout=settings.LEMONADE_TIMEOUT_SECONDS,
        )
        elapsed = round(time.perf_counter() - started, 3)
        usage = (resp.raw or {}).get("usage") or {}
        out[label] = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "content": resp.content,
            "wall_s": elapsed,
            "usage": usage,
            "timings": (resp.raw or {}).get("timings"),
        }
    if out["with_tools"].get("prompt_tokens") and out["no_tools"].get("prompt_tokens"):
        out["schema_token_cost"] = (
            out["with_tools"]["prompt_tokens"] - out["no_tools"]["prompt_tokens"]
        )
    return out


def _extract_llm_calls(transcript_path: Path) -> list[dict]:
    calls = []
    for line in transcript_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("type") != "llm_call":
            continue
        usage = rec.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        cached = details.get("cached_tokens")
        if cached is None:
            cached = usage.get("cached_tokens")
        timings = rec.get("timings") or {}
        prompt_tokens = usage.get("prompt_tokens")
        reprocessed = None
        if prompt_tokens is not None and cached is not None:
            reprocessed = prompt_tokens - cached
        calls.append(
            {
                "enable_thinking": rec.get("enable_thinking"),
                "discarded": rec.get("discarded", False),
                "timeout": rec.get("timeout"),
                "wall_clock_seconds": rec.get("wall_clock_seconds"),
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached,
                "reprocessed_tokens": reprocessed,
                "completion_tokens": usage.get("completion_tokens"),
                "prompt_tokens_details": details or None,
                "timings_prompt_n": timings.get("prompt_n"),
                "timings_prompt_ms": timings.get("prompt_ms"),
                "timings": timings or None,
                "finish_reason": rec.get("finish_reason"),
                "had_tool_calls": bool(rec.get("tool_calls")),
            }
        )
    return calls


def _cache_break_notes(calls: list[dict]) -> str:
    notes = []
    prev_cached = None
    for i, call in enumerate(calls):
        cached = call.get("cached_tokens")
        if prev_cached is not None and cached is not None and cached < prev_cached:
            notes.append(
                f"call[{i}] cached_tokens dropped {prev_cached} -> {cached} "
                "(possible cache break after history rewrite/compression)"
            )
        if cached is not None:
            prev_cached = cached
    if not notes:
        if all(c.get("cached_tokens") in (None, 0) for c in calls):
            return (
                "No cached_tokens reported (or all zero); cannot confirm cache reuse "
                "from usage.prompt_tokens_details."
            )
        return "No cached_tokens drop observed between successive llm_calls."
    return "; ".join(notes)


def measure_test_b(model: str | None = None) -> dict:
    from scripts.agent_loop import run_tool_rounds, system_prompt
    from agent.executor.guard import CallGuard
    from agent.transcript import Transcript
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider
    from security.gate import reset_session
    from tools.browser.browser_tools import close_session

    question = (
        "What molecule do mitochondria produce? Use the web and cite sources."
    )
    reset_session()
    close_session()
    provider = LemonadeProvider(model=model) if model else LemonadeProvider()
    transcript = Transcript()
    system = system_prompt()
    history = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=question),
    ]
    transcript.run_start(user_prompt=question, model=provider.model, system_prompt=system)
    started = time.perf_counter()
    try:
        response = run_tool_rounds(provider, history, CallGuard(), transcript)
        answer = response.content or ""
    finally:
        wall = round(time.perf_counter() - started, 3)
        transcript.run_end(wall_clock_seconds=wall, rounds=transcript.rounds, round_cap_hit=transcript.round_cap_hit)
        path = transcript.path
        transcript.close()
        close_session()
    calls = _extract_llm_calls(path)
    correct = "ATP" in answer.upper() or "adenosine triphosphate" in answer.lower()
    return {
        "task": "Test B mitochondria",
        "question": question,
        "wall_s": wall,
        "correct": correct,
        "answer_preview": answer[:400],
        "transcript": str(path),
        "llm_calls": calls,
        "cache_notes": _cache_break_notes(calls),
    }


def measure_atp_chat(model: str | None = None) -> dict:
    from tests.support import answer_by_action
    from scripts.chat import end_session, new_session, run_user_turn
    from scripts.agent_loop import QUOTE_CHECK_NOTE
    from llm.lemonade.provider import LemonadeProvider
    from security.gate import reset_session
    from tools.browser.browser_tools import close_session
    import re

    turn1 = (
        "Open https://en.wikipedia.org in the browser and search for ATP synthase."
    )
    turn2 = "What is the first sentence of that article? Quote it exactly."
    # Independent first sentence
    headers = {"User-Agent": "MiniAI-measure/1.0"}
    api = "https://en.wikipedia.org/api/rest_v1/page/summary/ATP_synthase"
    extract = requests.get(api, timeout=30, headers=headers).json().get("extract") or ""
    m = re.match(r"(.+?\.)(\s|$)", extract.strip(), re.DOTALL)
    real = m.group(1).strip() if m else ""

    reset_session()
    close_session()
    provider = LemonadeProvider(model=model) if model else LemonadeProvider()
    session = new_session(provider)
    mapping = {
        "browser_open": "yes",
        "browser_type": "browser_type",
        "browser_click": "yes",
        "fetch_url": "yes",
    }
    started = time.perf_counter()
    a1 = a2 = ""
    err = None
    try:
        with answer_by_action(mapping):
            a1 = run_user_turn(session, turn1)
            a2 = run_user_turn(session, turn2)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    wall = round(time.perf_counter() - started, 3)
    path = session.transcript.path if session.transcript else None
    end_session(session)
    calls = _extract_llm_calls(path) if path else []

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.lower().replace("*", "").replace("_", "")).strip()

    has_sentence = bool(a2) and real and _norm(real) in _norm(a2)
    has_note = QUOTE_CHECK_NOTE in a2
    return {
        "task": "two-turn ATP chat",
        "wall_s": wall,
        "error": err,
        "correct": bool(has_sentence and not has_note),
        "has_real_sentence": has_sentence,
        "has_quote_note": has_note,
        "real_first_sentence": real,
        "turn2_preview": (a2 or "")[:400],
        "transcript": str(path) if path else None,
        "llm_calls": calls,
        "cache_notes": _cache_break_notes(calls),
    }


def measure_root_count(model: str | None = None) -> dict:
    from scripts.agent_loop import run_tool_rounds, system_prompt
    from agent.executor.guard import CallGuard
    from agent.transcript import Transcript
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider
    from security.gate import reset_session
    from tools.browser.browser_tools import close_session

    expected = len(os.listdir(ROOT))
    question = (
        f'How many entries are in the project root directory "{ROOT}"? '
        "Use tools; report the exact count."
    )
    reset_session()
    close_session()
    provider = LemonadeProvider(model=model) if model else LemonadeProvider()
    transcript = Transcript()
    system = system_prompt()
    history = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=question),
    ]
    transcript.run_start(user_prompt=question, model=provider.model, system_prompt=system)
    started = time.perf_counter()
    try:
        response = run_tool_rounds(provider, history, CallGuard(), transcript)
        answer = response.content or ""
    finally:
        wall = round(time.perf_counter() - started, 3)
        transcript.run_end(wall_clock_seconds=wall, rounds=transcript.rounds, round_cap_hit=transcript.round_cap_hit)
        path = transcript.path
        transcript.close()
        close_session()
    correct = str(expected) in answer
    calls = _extract_llm_calls(path)
    return {
        "task": "root-count",
        "expected": expected,
        "correct": correct,
        "wall_s": wall,
        "answer_preview": answer[:300],
        "transcript": str(path),
        "llm_calls": calls,
        "per_call_s": [c.get("wall_clock_seconds") for c in calls],
    }


def measure_test_a(model: str | None = None) -> dict:
    from scripts.agent_loop import run_tool_rounds, system_prompt
    from agent.executor.guard import CallGuard
    from agent.transcript import Transcript
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider
    from security.gate import reset_session
    from tools.browser.browser_tools import close_session

    question = (
        "What is the latest stable version of Python? Use the web and cite sources."
    )
    reset_session()
    close_session()
    provider = LemonadeProvider(model=model) if model else LemonadeProvider()
    transcript = Transcript()
    system = system_prompt()
    history = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=question),
    ]
    transcript.run_start(user_prompt=question, model=provider.model, system_prompt=system)
    started = time.perf_counter()
    try:
        response = run_tool_rounds(provider, history, CallGuard(), transcript)
        answer = response.content or ""
    finally:
        wall = round(time.perf_counter() - started, 3)
        transcript.run_end(wall_clock_seconds=wall, rounds=transcript.rounds, round_cap_hit=transcript.round_cap_hit)
        path = transcript.path
        transcript.close()
        close_session()
    # Soft correctness: mentions 3.1x or 3.14/3.15
    import re

    correct = bool(re.search(r"3\.\d+", answer))
    calls = _extract_llm_calls(path)
    return {
        "task": "Test A latest Python",
        "correct": correct,
        "wall_s": wall,
        "answer_preview": answer[:400],
        "transcript": str(path),
        "llm_calls": calls,
        "per_call_s": [c.get("wall_clock_seconds") for c in calls],
    }


def ensure_model_loaded(model: str, ctx: int = 16384) -> dict:
    """Load model with ctx without --save-options. Returns RAM snapshot."""
    _lemonade("unload", "--all", timeout=120)
    time.sleep(2)
    before = _ram_gb()
    proc = _lemonade("load", model, "--ctx-size", str(ctx), timeout=600)
    time.sleep(3)
    after = _ram_gb()
    return {
        "model": model,
        "load_returncode": proc.returncode,
        "load_stdout": (proc.stdout or "")[-2000:],
        "load_stderr": (proc.stderr or "")[-2000:],
        "ram_before": before,
        "ram_after": after,
        "fits": after["used_gb"] <= RAM_LIMIT_GB,
    }


def reload_qwen14_saved() -> dict:
    """Reload Qwen3-14B normally (uses saved options) and confirm ctx 16384."""
    _lemonade("unload", "--all", timeout=120)
    time.sleep(2)
    proc = _lemonade("load", "Qwen3-14B-GGUF", timeout=600)
    time.sleep(2)
    status = _lemonade("status", timeout=60)
    text = (status.stdout or "") + (status.stderr or "")
    return {
        "load_returncode": proc.returncode,
        "status_returncode": status.returncode,
        "status_text": text[-4000:],
        "mentions_16384": "16384" in text,
        "mentions_14b": "Qwen3-14B" in text or "14B" in text,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results: dict = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "usable_ram_gb": USABLE_RAM_GB,
        "ram_limit_gb": RAM_LIMIT_GB,
    }

    print("=== lemonade list (Qwen3 filter) ===")
    listed = _lemonade("list", timeout=60)
    qwen_lines = [
        line
        for line in (listed.stdout or "").splitlines()
        if "Qwen3-8B" in line or "Qwen3-30B-A3B" in line or "Qwen3-14B-GGUF" in line
    ]
    results["lemonade_list_qwen"] = qwen_lines
    print("\n".join(qwen_lines))

    print("=== schema cost ===")
    results["schema_cost"] = measure_schema_cost()
    print(json.dumps(results["schema_cost"], indent=2)[:1500])

    print("=== Test B (cache) ===")
    results["test_b_cache"] = measure_test_b()
    print(
        "wall",
        results["test_b_cache"]["wall_s"],
        "correct",
        results["test_b_cache"]["correct"],
        "cache_notes",
        results["test_b_cache"]["cache_notes"],
    )

    print("=== ATP chat (cache) ===")
    # Kill leftover playwright
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.ExecutablePath -like '*ms-playwright*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
            ],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass
    results["atp_chat_cache"] = measure_atp_chat()
    print(
        "wall",
        results["atp_chat_cache"]["wall_s"],
        "correct",
        results["atp_chat_cache"]["correct"],
        "cache_notes",
        results["atp_chat_cache"]["cache_notes"],
    )

    # Baseline 14B suite
    print("=== Qwen3-14B baseline suite ===")
    m14 = "Qwen3-14B-GGUF"
    baseline = {"model": m14, "runs": {}}
    baseline["runs"]["test_a_1"] = measure_test_a(m14)
    baseline["runs"]["test_a_2"] = measure_test_a(m14)
    baseline["runs"]["test_b"] = measure_test_b(m14)
    baseline["runs"]["root_count"] = measure_root_count(m14)
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.ExecutablePath -like '*ms-playwright*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
            ],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass
    baseline["runs"]["atp_chat"] = measure_atp_chat(m14)
    results["baseline_14b"] = baseline

    # Alternative models
    candidates = [
        ("Qwen3-8B-GGUF", 5.25),
        ("Qwen3-30B-A3B-GGUF", 17.40),
    ]
    alt: dict = {"offered": [], "evals": {}}
    for name, size_gb in candidates:
        offered = any(name in line for line in (listed.stdout or "").splitlines())
        entry = {
            "name": name,
            "size_gb": size_gb,
            "offered": offered,
            "leq_18gb": size_gb <= 18,
        }
        alt["offered"].append(entry)
        if not (offered and entry["leq_18gb"]):
            continue
        print(f"=== pull {name} ===")
        pull = _lemonade("pull", name, timeout=7200)
        entry["pull_returncode"] = pull.returncode
        entry["pull_tail"] = ((pull.stdout or "") + (pull.stderr or ""))[-1500:]
        print(f"pull rc={pull.returncode}")
        print(f"=== load {name} ctx 16384 (no --save-options) ===")
        load_info = ensure_model_loaded(name, ctx=16384)
        entry["load"] = load_info
        print(
            "RAM used",
            load_info["ram_after"]["used_gb"],
            "fits",
            load_info["fits"],
        )
        if not load_info["fits"]:
            print(f"{name} exceeds 21 GB used; unloading")
            _lemonade("unload", "--all", timeout=120)
            continue
        print(f"=== eval suite on {name} ===")
        suite = {"model": name, "runs": {}}
        suite["runs"]["test_a_1"] = measure_test_a(name)
        suite["runs"]["test_a_2"] = measure_test_a(name)
        suite["runs"]["test_b"] = measure_test_b(name)
        suite["runs"]["root_count"] = measure_root_count(name)
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                    "Where-Object { $_.ExecutablePath -like '*ms-playwright*' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
                ],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass
        suite["runs"]["atp_chat"] = measure_atp_chat(name)
        alt["evals"][name] = suite
        _lemonade("unload", "--all", timeout=120)

    results["alternative_models"] = alt

    # Restore 14B with saved options
    print("=== restore Qwen3-14B ===")
    results["restore_14b"] = reload_qwen14_saved()
    print(
        "mentions_16384",
        results["restore_14b"]["mentions_16384"],
        "status_tail",
        results["restore_14b"]["status_text"][-500:],
    )

    results["finished"] = datetime.now().isoformat(timespec="seconds")
    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE {RESULTS}")
    print(RESULTS.name)


if __name__ == "__main__":
    main()
