"""Round 6 Part 4: append PDF/knowledge page citations from search_knowledge hits."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional

# Tuned: require meaningful overlap; avoid citing unrelated top-k noise.
DEFAULT_OVERLAP_THRESHOLD = 0.12
MAX_CITATIONS = 3
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "with",
        "as",
        "by",
        "from",
        "it",
        "at",
        "page",
        "source",
    }
)


def tokenize(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if len(t) > 2 and t.lower() not in _STOP
    }


def token_overlap(answer: str, chunk: str) -> float:
    """Jaccard-like overlap of answer tokens vs chunk tokens (answer-weighted)."""
    a = tokenize(answer)
    c = tokenize(chunk)
    if not a or not c:
        return 0.0
    inter = a & c
    # Fraction of answer tokens that appear in the chunk (what the answer relies on)
    return len(inter) / max(1, len(a))


def _unwrap_content(content: str) -> str:
    """Strip untrusted file wrappers from indexed chunk text."""
    text = content or ""
    begin = "<<<BEGIN UNTRUSTED FILE CONTENT>>>"
    end = "<<<END UNTRUSTED FILE CONTENT>>>"
    if begin in text and end in text:
        text = text.split(begin, 1)[1].split(end, 1)[0]
    return text.strip()


def parse_knowledge_hits(tool_texts: Iterable[str]) -> list[dict[str, Any]]:
    """Extract search_knowledge hit dicts from tool result strings."""
    hits: list[dict[str, Any]] = []
    for text in tool_texts or []:
        raw = (text or "").strip()
        if not raw.startswith("["):
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            if "source_path" not in item and "content" not in item:
                continue
            hits.append(item)
    return hits


def pick_citations(
    answer: str,
    hits: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    max_citations: int = MAX_CITATIONS,
) -> list[tuple[str, Optional[int], float]]:
    """Return (display_file, page_number, score) sorted by score desc."""
    scored: list[tuple[str, Optional[int], float]] = []
    seen: set[tuple[str, Optional[int]]] = set()
    for hit in hits:
        content = _unwrap_content(str(hit.get("content") or ""))
        score = token_overlap(answer, content)
        if score < threshold:
            continue
        src = str(hit.get("source_path") or "document")
        display = Path(src).name or src
        page = hit.get("page_number")
        try:
            page_i: Optional[int] = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_i = None
        key = (display, page_i)
        if key in seen:
            # Keep higher score
            for i, (d, p, s) in enumerate(scored):
                if (d, p) == key and score > s:
                    scored[i] = (display, page_i, score)
            continue
        seen.add(key)
        scored.append((display, page_i, score))
    scored.sort(key=lambda t: (-t[2], t[0], t[1] or 0))
    return scored[:max_citations]


def format_citation_lines(
    citations: list[tuple[str, Optional[int], float]],
) -> str:
    if not citations:
        return ""
    lines = []
    for display, page, _score in citations:
        if page is not None:
            lines.append(f"Source: {display}, page {page}")
        else:
            lines.append(f"Source: {display}")
    return "\n".join(lines)


def append_pdf_citations(
    answer: str,
    turn_evidence: Iterable[str],
    *,
    tools_used: Optional[set[str]] = None,
    threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> tuple[str, dict[str, Any]]:
    """Append Source lines when search_knowledge evidence overlaps the answer."""
    from config import settings

    meta: dict[str, Any] = {"applied": False, "citations": []}
    if not getattr(settings, "FEATURE_PDF_CITATIONS", True):
        return answer, meta
    if tools_used is not None and "search_knowledge" not in tools_used:
        # Still try parsing evidence in case tool name tracking missed
        hits = parse_knowledge_hits(turn_evidence)
        if not hits:
            return answer, meta
    else:
        hits = parse_knowledge_hits(turn_evidence)
    if not hits:
        return answer, meta
    # Idempotent: already has Source: lines
    if re.search(r"(?im)^Source:\s+\S+", answer or ""):
        meta["applied"] = False
        meta["skipped"] = "already_present"
        return answer, meta
    citations = pick_citations(answer or "", hits, threshold=threshold)
    block = format_citation_lines(citations)
    if not block:
        return answer, meta
    out = (answer or "").rstrip() + "\n\n" + block
    meta["applied"] = True
    meta["citations"] = [
        {"file": f, "page": p, "score": round(s, 4)} for f, p, s in citations
    ]
    return out, meta
