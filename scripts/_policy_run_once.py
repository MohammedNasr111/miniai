"""One policy-comparison run (invoked in a fresh process)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Policy must be set in the environment before importing settings.
# Parent sets MINIAI_THINKING_POLICY.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.support import answer_by_action

import scripts.agent_loop as agent_loop
from agent.executor.guard import CallGuard
from agent.transcript import Transcript
from config import settings
from llm.base import ChatMessage
from llm.lemonade.provider import LemonadeProvider
from security.gate import reset_session
from tools.browser.browser_tools import close_session


def _analyze(transcript_path: Path, task: str, final: str) -> dict:
    import re

    events = [
        json.loads(line)
        for line in transcript_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tools = [e for e in events if e.get("type") == "tool_call"]
    llms = [e for e in events if e.get("type") == "llm_call"]
    run_end = next((e for e in events if e.get("type") == "run_end"), {})
    tool_text = "\n".join(
        (e.get("result") or "") + "\n" + json.dumps(e.get("args") or {})
        for e in tools
    )
    names = [e.get("name") for e in tools]
    urls_seen = re.findall(r"https?://[^\s\"'<>]+", tool_text)

    if task == "W":
        used_type = "browser_type" in names
        article = any("ATP_synthase" in u for u in urls_seen)
        used_submit = any(
            e.get("name") == "browser_type"
            and bool((e.get("args") or {}).get("submit"))
            for e in tools
        )
        claim_bits = [
            p
            for p in (
                "ATP synthase is an enzyme",
                "adenosine triphosphate",
                "catalyzes the formation",
            )
            if p.lower() in (final or "").lower()
        ]
        # Strict: claim must appear in a tool result whose page URL
        # contains ATP_synthase (not merely in any tool text / web_research).
        article_results = []
        for e in tools:
            result = e.get("result") or ""
            m = re.search(r"(?m)^URL:\s*(.+)$", result)
            if m and "ATP_synthase" in m.group(1):
                article_results.append(result)
        article_blob = "\n".join(article_results)
        grounded = bool(claim_bits) and bool(article_results) and all(
            bit.lower() in article_blob.lower() for bit in claim_bits
        )
        return {
            "completed": used_type and article,
            "grounded": grounded,
            "used_browser_type": used_type,
            "used_submit": used_submit,
            "article_reached": article,
            "n_llm": len(llms),
            "wall": run_end.get("wall_clock_seconds"),
            "tools": [
                {
                    "name": e.get("name"),
                    "args": e.get("args"),
                    "outcome": e.get("outcome"),
                }
                for e in tools
            ],
            "final": final,
            "transcript": str(transcript_path),
        }

    downloads = any("python.org" in u and "download" in u.lower() for u in urls_seen)
    clicked = "browser_click" in names
    versions = re.findall(r"Python\s+(\d+\.\d+(?:\.\d+)?)", final or "", flags=re.I)
    versions += re.findall(r"\b(\d+\.\d+\.\d+)\b", final or "")
    key_version = versions[0] if versions else None
    grounded = bool(key_version) and key_version in tool_text
    return {
        "completed": downloads and clicked,
        "grounded": grounded,
        "downloads_reached": downloads,
        "clicked": clicked,
        "key_version": key_version,
        "n_llm": len(llms),
        "wall": run_end.get("wall_clock_seconds"),
        "tools": [
            {
                "name": e.get("name"),
                "args": e.get("args"),
                "outcome": e.get("outcome"),
            }
            for e in tools
        ],
        "final": final,
        "transcript": str(transcript_path),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    policy = sys.argv[1]
    task = sys.argv[2]
    run_id = int(sys.argv[3])
    prompt = sys.argv[4]
    print(f"THINKING_POLICY_SETTING={settings.THINKING_POLICY} env_arg={policy}")
    if settings.THINKING_POLICY != policy:
        print(
            f"WARN: settings.THINKING_POLICY={settings.THINKING_POLICY!r} "
            f"!= requested {policy!r}"
        )
    agent_loop._require_lemonade()
    reset_session()
    close_session()
    provider = LemonadeProvider()
    transcript = Transcript()
    started = time.perf_counter()
    system = agent_loop.system_prompt()
    history = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=prompt),
    ]
    mapping = {
        "browser_open": "yes",
        "browser_type": "browser_type",
        "browser_click": "yes",
    }
    final = ""
    try:
        transcript.run_start(
            user_prompt=prompt,
            model=provider.model,
            system_prompt=system,
        )
        with answer_by_action(mapping) as prompt_log:
            guard = CallGuard()
            response = agent_loop.run_tool_rounds(
                provider, history, guard, transcript
            )
        print("=== PROMPT LOG ===")
        for action, p, answer in prompt_log:
            print(f"Action={action!r} answer={answer!r} prompt={p!r}")
        final = response.content or ""
        print(f"Final answer: {final}")
        wall = round(time.perf_counter() - started, 3)
        transcript.run_end(
            wall_clock_seconds=wall,
            rounds=transcript.rounds,
            round_cap_hit=transcript.round_cap_hit,
        )
        print(f"WALL={wall}")
        print(f"Transcript: {transcript.path}")
        analysis = _analyze(Path(transcript.path), task, final)
        analysis["policy"] = policy
        analysis["task"] = task
        analysis["run_id"] = run_id
        print("RESULT_JSON=" + json.dumps(analysis, ensure_ascii=False))
    finally:
        close_session()
        transcript.close()


if __name__ == "__main__":
    main()
