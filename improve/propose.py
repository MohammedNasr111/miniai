"""Propose playbook edits from failed eval runs (dev sets only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from improve.filter import extract_failure_context, filter_candidate

DEV_ABILITIES = frozenset({"freshness", "web", "knowledge"})
BLOCKED_ABILITIES = frozenset({"freshness_holdout", "safety"})
EVIDENCE_MAX = 1500
RUNS_DIR = PROJECT_ROOT / "improve" / "runs"


def _load_eval(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_prompts() -> dict[str, str]:
    """Map task id → first prompt from YAML."""
    import yaml

    out: dict[str, str] = {}
    tasks_dir = PROJECT_ROOT / "eval" / "tasks"
    for p in tasks_dir.glob("*.yaml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        prompts = data.get("prompts") or []
        if isinstance(prompts, str):
            prompts = [prompts]
        if prompts:
            out[str(data.get("id"))] = str(prompts[0])
    return out


def _find_agent_log_for_prompt(prompt: str, logs_dir: Path) -> Path | None:
    needle = prompt.strip()[:80]
    if not needle:
        return None
    candidates = sorted(logs_dir.glob("agent_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates[:200]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle in text:
            return path
    return None


def _evidence_from_log(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    chunks: list[str] = []
    # Prefer untrusted web content blocks and tool results.
    for m in re.finditer(
        r"<<<BEGIN UNTRUSTED WEB CONTENT>>>(.*?)<<<END UNTRUSTED WEB CONTENT>>>",
        text,
        re.DOTALL,
    ):
        chunks.append(m.group(1).strip())
    if not chunks:
        for line in text.splitlines():
            if '"type": "tool_result"' in line or '"type": "tool_call"' in line:
                chunks.append(line[:400])
    blob = "\n---\n".join(chunks)
    if len(blob) > EVIDENCE_MAX:
        blob = blob[: EVIDENCE_MAX - 20] + "\n...[truncated]..."
    return blob


def collect_failures(eval_data: dict[str, Any]) -> list[dict[str, Any]]:
    prompts_by_id = _task_prompts()
    logs_dir = PROJECT_ROOT / "logs"
    rows = eval_data.get("raw_runs") or eval_data.get("results") or []
    failures: list[dict[str, Any]] = []
    for r in rows:
        if r.get("pass") is not False:
            continue
        ability = str(r.get("ability") or "")
        if ability in BLOCKED_ABILITIES:
            continue
        if ability not in DEV_ABILITIES:
            continue
        tid = str(r.get("id") or "")
        prompt = prompts_by_id.get(tid, "")
        answers = r.get("answers") or []
        answer = "\n".join(answers) if isinstance(answers, list) else str(answers)
        log_path = _find_agent_log_for_prompt(prompt, logs_dir) if prompt else None
        failures.append(
            {
                "task_id": tid,
                "ability": ability,
                "prompt": prompt,
                "answer": answer,
                "reason": str(r.get("reason") or ""),
                "evidence": _evidence_from_log(log_path),
                "log": str(log_path) if log_path else None,
            }
        )
    return failures


def _ask_model(failures: list[dict[str, Any]], max_n: int) -> list[dict[str, str]]:
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider

    payload = []
    for f in failures:
        payload.append(
            {
                "task_id": f["task_id"],
                "prompt": f["prompt"],
                "answer": f["answer"][:800],
                "reason": f["reason"],
                "evidence_excerpt": f["evidence"][:EVIDENCE_MAX],
            }
        )
    system = (
        "You propose short, GENERAL playbook instructions to improve an AI agent. "
        "Each instruction must be at most 300 characters, apply across many tasks, "
        "and must NOT name specific products, versions, tool names, or permission words. "
        "Return JSON only: {\"candidates\": [{\"instruction\": \"...\", \"rationale\": \"...\"}]} "
        f"with at most {max_n} candidates."
    )
    user = (
        "Failed eval cases (dev set only):\n"
        + json.dumps(payload, indent=2)
        + "\n\nPropose up to "
        + str(max_n)
        + " general playbook lines."
    )
    provider = LemonadeProvider(enable_thinking=True)
    resp = provider.chat(
        [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ],
        tools=None,
        enable_thinking=True,
    )
    content = (resp.content or "").strip()
    # Strip markdown fences if present.
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try to find a JSON object
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    cands = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(cands, list):
        return []
    out: list[dict[str, str]] = []
    for c in cands[:max_n]:
        if not isinstance(c, dict):
            continue
        instr = str(c.get("instruction") or "").strip()
        rat = str(c.get("rationale") or "").strip().splitlines()[0] if c.get("rationale") else ""
        if instr:
            out.append({"instruction": instr[:300], "rationale": rat[:300]})
    return out


def propose(
    eval_path: Path,
    *,
    max_n: int = 2,
    model_candidates: list[dict[str, str]] | None = None,
) -> Path:
    eval_data = _load_eval(eval_path)
    failures = collect_failures(eval_data)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = RUNS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    if model_candidates is None:
        raw_cands = _ask_model(failures, max_n) if failures else []
    else:
        raw_cands = model_candidates[:max_n]

    ctx = extract_failure_context(failures)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for i, c in enumerate(raw_cands, start=1):
        ok, reason = filter_candidate(c["instruction"], context=ctx, failures=failures)
        row = {
            "id": f"c{i}",
            "instruction": c["instruction"],
            "rationale": c.get("rationale") or "",
            "filter_ok": ok,
            "filter_reason": reason,
        }
        if ok:
            accepted.append(row)
        else:
            rejected.append(row)

    proposal = {
        "stamp": stamp,
        "source_eval": str(eval_path),
        "failures": failures,
        "filter_context": ctx,
        "accepted": accepted,
        "rejected": rejected,
        "all_candidates": accepted + rejected,
    }
    (out_dir / "proposal.json").write_text(
        json.dumps(proposal, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Proposal {stamp}",
        "",
        f"Source: `{eval_path}`",
        f"Failures considered: {len(failures)}",
        "",
        "## Accepted",
        "",
    ]
    for c in accepted:
        lines.append(f"- **{c['id']}**: {c['instruction']}")
        lines.append(f"  - rationale: {c['rationale']}")
    if not accepted:
        lines.append("- (none)")
    lines.extend(["", "## Rejected by filter", ""])
    for c in rejected:
        lines.append(f"- **{c['id']}**: {c['instruction']}")
        lines.append(f"  - filter: {c['filter_reason']}")
    if not rejected:
        lines.append("- (none)")
    (out_dir / "proposal.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out_dir / 'proposal.json'}")
    print(f"accepted={len(accepted)} rejected={len(rejected)}")
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose playbook edits from eval failures")
    parser.add_argument("--from", dest="eval_json", required=True, help="Eval JSON path")
    parser.add_argument("--max", type=int, default=2, help="Max candidates to ask for")
    args = parser.parse_args(argv)
    path = Path(args.eval_json)
    if not path.is_file():
        print(f"Missing eval JSON: {path}")
        return 1
    propose(path, max_n=args.max)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
