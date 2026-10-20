"""Draft -> check -> fix: verify factual claims against this turn's evidence.

Default OFF (settings.CHECKER / MINIAI_CHECKER). Never blocks an answer on
parser failure — bad JSON is treated as verdict \"ok\" and logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable, Optional

from config import settings
from llm.base import ChatMessage

logger = logging.getLogger(__name__)

EVIDENCE_TOOLS = frozenset(
    {
        "web_research",
        "web_search",
        "fetch_url",
        "browser_open",
        "browser_observe",
        "browser_click",
        "browser_type",
        "search_knowledge",
        "read_file",
        "desktop_read_window",
        "run_file",
        "run_code",
        "run_tests",
    }
)

# ~6K tokens ≈ 24K characters of evidence text.
_EVIDENCE_CHAR_BUDGET = 24_000

_CHECK_SCHEMA_HINT = """{
  "verdict": "ok" | "fix",
  "claims": [
    {
      "claim": "<short factual claim from the draft>",
      "status": "supported" | "contradicted" | "unsupported",
      "source_url": "<url from evidence or empty string>",
      "quote": "<verbatim substring copied from the evidence>"
    }
  ],
  "notes": "<optional short note>"
}"""


def checker_enabled() -> bool:
    raw = os.environ.get("MINIAI_CHECKER")
    if raw is None or raw.strip() == "":
        raw = getattr(settings, "CHECKER", "off")
    return str(raw).strip().lower() == "on"


def trim_evidence(
    evidence: list[str],
    question: str,
    draft: str,
    budget: int = _EVIDENCE_CHAR_BUDGET,
) -> str:
    """Join evidence chunks, preferring those that share keywords with Q/draft."""
    if not evidence:
        return ""
    keywords = {
        w.lower()
        for w in re.findall(r"[A-Za-z0-9.]{3,}", f"{question} {draft}")
    }
    scored: list[tuple[int, int, str]] = []
    for i, chunk in enumerate(evidence):
        text = chunk or ""
        low = text.lower()
        score = sum(1 for w in keywords if w in low)
        scored.append((score, -i, text))  # higher score, earlier original order
    scored.sort(reverse=True)
    parts: list[str] = []
    used = 0
    for _score, _neg_i, text in scored:
        if used >= budget:
            break
        piece = text if used + len(text) <= budget else text[: budget - used]
        if not piece:
            continue
        parts.append(piece)
        used += len(piece)
    return "\n\n---\n\n".join(parts)


def _quote_in_evidence(quote: str, evidence_parts: list[str]) -> bool:
    from scripts.agent_loop import normalize_for_quote_check

    needle = normalize_for_quote_check(quote or "")
    if not needle:
        return False
    return any(needle in normalize_for_quote_check(e) for e in evidence_parts if e)


def verify_claim_quotes(
    claims: list[dict[str, Any]], evidence_parts: list[str]
) -> list[dict[str, Any]]:
    """Downgrade claims whose quote is not word-for-word in the evidence."""
    out: list[dict[str, Any]] = []
    for raw in claims:
        claim = dict(raw) if isinstance(raw, dict) else {}
        quote = str(claim.get("quote") or "")
        status = str(claim.get("status") or "unsupported")
        if quote and not _quote_in_evidence(quote, evidence_parts):
            claim["status"] = "unsupported"
            claim["quote_verified"] = False
            logger.info(
                "checker: quote not found in evidence; downgraded claim %r",
                claim.get("claim"),
            )
        else:
            claim["quote_verified"] = bool(quote) and status != "unsupported"
            if status not in ("supported", "contradicted", "unsupported"):
                claim["status"] = "unsupported"
        out.append(claim)
    return out


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    # Strip markdown fences if present.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_result(data: dict[str, Any]) -> dict[str, Any]:
    claims_in = data.get("claims") or []
    claims: list[dict[str, Any]] = []
    if isinstance(claims_in, list):
        for c in claims_in:
            if not isinstance(c, dict):
                continue
            status = str(c.get("status") or "unsupported").lower()
            if status not in ("supported", "contradicted", "unsupported"):
                status = "unsupported"
            claims.append(
                {
                    "claim": str(c.get("claim") or ""),
                    "status": status,
                    "source_url": str(c.get("source_url") or ""),
                    "quote": str(c.get("quote") or ""),
                }
            )
    verdict = str(data.get("verdict") or "ok").lower()
    if any(c["status"] == "contradicted" for c in claims):
        verdict = "fix"
    elif verdict not in ("ok", "fix"):
        verdict = "ok"
    if verdict == "fix" and not any(c["status"] == "contradicted" for c in claims):
        verdict = "ok"
    return {
        "verdict": verdict,
        "claims": claims,
        "notes": str(data.get("notes") or ""),
    }


def check_answer(
    question: str,
    draft: str,
    evidence: list[str],
    provider: Any = None,
    transcript: Any = None,
) -> dict[str, Any]:
    """Compare draft claims to evidence. Returns ok/fix result dict."""
    evidence_parts = [e for e in evidence if e]
    trimmed = trim_evidence(evidence_parts, question, draft)
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    system = (
        "You are a careful fact-checker for MiniAI. Today is "
        f"{today}. Compare each factual claim in the DRAFT with the EVIDENCE. "
        "A claim is contradicted if the evidence states something different. "
        "Check that every cited URL actually supports the sentence it is "
        "attached to. Prefer the most authoritative and most recent source "
        "using today's date. Copy quotes VERBATIM from the evidence — never "
        "paraphrase a quote. Reply with JSON only, no markdown, matching:\n"
        + _CHECK_SCHEMA_HINT
    )
    user = (
        f"QUESTION:\n{question}\n\nDRAFT:\n{draft}\n\nEVIDENCE:\n{trimmed}"
    )
    raw_text = ""
    try:
        if provider is None:
            raise RuntimeError("no provider")
        kwargs: dict[str, Any] = {
            "enable_thinking": True,
            "timeout": getattr(
                settings, "LEMONADE_SYNTHESIS_TIMEOUT_SECONDS", 450
            ),
        }
        # Prefer Lemonade/OpenAI JSON mode when available.
        kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = provider.chat(
                [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ],
                tools=None,
                **kwargs,
            )
        except Exception:
            kwargs.pop("response_format", None)
            resp = provider.chat(
                [
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ],
                tools=None,
                **kwargs,
            )
        raw_text = resp.content or ""
    except Exception as exc:
        logger.warning("checker model call failed: %s — treating as ok", exc)
        result = {
            "verdict": "ok",
            "claims": [],
            "notes": f"checker_error: {type(exc).__name__}",
            "parse_ok": False,
        }
        if transcript is not None:
            transcript.write("check", result=result, draft=draft, raw="")
        return result

    parsed = _extract_json_object(raw_text)
    if parsed is None:
        logger.warning("checker bad JSON — treating as ok")
        result = {
            "verdict": "ok",
            "claims": [],
            "notes": "bad_json",
            "parse_ok": False,
        }
        if transcript is not None:
            transcript.write("check", result=result, draft=draft, raw=raw_text)
        return result

    result = _normalize_result(parsed)
    result["claims"] = verify_claim_quotes(result["claims"], evidence_parts)
    if any(c["status"] == "contradicted" for c in result["claims"]):
        result["verdict"] = "fix"
    else:
        result["verdict"] = "ok"
    result["parse_ok"] = True
    if transcript is not None:
        transcript.write("check", result=result, draft=draft, raw=raw_text)
    return result


def rewrite_answer(
    question: str,
    draft: str,
    check_result: dict[str, Any],
    provider: Any,
    transcript: Any = None,
) -> str:
    """One rewrite call with thinking ON; returns corrected answer text."""
    contradicted = [
        c for c in (check_result.get("claims") or []) if c.get("status") == "contradicted"
    ]
    lines = []
    for c in contradicted:
        lines.append(
            f"- Claim: {c.get('claim')}\n"
            f"  Quote from evidence: {c.get('quote')}\n"
            f"  Source: {c.get('source_url') or '(none)'}"
        )
    system = (
        "You correct MiniAI draft answers using verified evidence quotes. "
        "Correct the answer. If sources truly conflict, say so and name which "
        "source says what. Do not invent facts. Keep citations. Reply with "
        "only the corrected answer text (markdown allowed), no preamble."
    )
    user = (
        f"QUESTION:\n{question}\n\nDRAFT:\n{draft}\n\n"
        f"CONTRADICTED CLAIMS:\n" + "\n".join(lines)
    )
    resp = provider.chat(
        [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ],
        tools=None,
        enable_thinking=True,
        timeout=getattr(settings, "LEMONADE_SYNTHESIS_TIMEOUT_SECONDS", 450),
    )
    rewritten = (resp.content or "").strip() or draft
    if transcript is not None:
        transcript.write(
            "check_fix",
            draft=draft,
            rewritten=rewritten,
            claims=contradicted,
        )
    return rewritten


def maybe_check_and_fix(
    *,
    provider: Any,
    question: str,
    draft: str,
    evidence: list[str],
    tools_used: set[str],
    transcript: Any = None,
    on_checking: Optional[Callable[[], None]] = None,
) -> tuple[str, Optional[dict[str, Any]]]:
    """Run checker if enabled and evidence tools were used. At most one fix."""
    if not checker_enabled():
        return draft, None
    if not (tools_used & EVIDENCE_TOOLS):
        return draft, None
    if on_checking is not None:
        try:
            on_checking()
        except Exception:
            pass
    result = check_answer(
        question, draft, evidence, provider=provider, transcript=transcript
    )
    if result.get("verdict") != "fix":
        return draft, result
    try:
        fixed = rewrite_answer(
            question, draft, result, provider=provider, transcript=transcript
        )
    except Exception as exc:
        logger.warning("checker rewrite failed: %s — keeping draft", exc)
        result["rewrite_error"] = type(exc).__name__
        return draft, result
    result["fixed"] = True
    result["draft"] = draft
    return fixed, result
