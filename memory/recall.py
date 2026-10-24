"""Automatic recall of relevant long-term memories for each user turn."""

from __future__ import annotations

import math
import re
from typing import Any, Optional

from memory.database.db import list_memories

MEMORY_HEADER = "Things the user asked you to remember (from memory):"
MEMORY_FOOTER = "(end of remembered items)"

# Tuned so "favourite colour" hits a teal preference, but "weather today" does not.
DEFAULT_THRESHOLD = 0.22
DEFAULT_TOP_K = 5
_TOKEN_RE = re.compile(r"[a-z0-9']+", re.I)


_ALIASES = {
    "favourite": "favorite",
    "colour": "color",
    "colours": "colors",
    "remembered": "remember",
    "preference": "prefer",
}


def _tokens(text: str) -> set[str]:
    stop = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "my",
        "your",
        "what",
        "whats",
        "what's",
        "do",
        "does",
        "did",
        "me",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "about",
        "please",
        "tell",
        "know",
        "can",
        "you",
        "i",
        "it",
        "user",
        "users",
    }
    out: set[str] = set()
    for t in _TOKEN_RE.findall(text or ""):
        low = t.lower()
        if low in stop or len(low) <= 1:
            continue
        out.add(_ALIASES.get(low, low))
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _cosine(u: list[float], v: list[float]) -> float:
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(x * y for x, y in zip(u, v))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    if nu <= 0 or nv <= 0:
        return 0.0
    return dot / (nu * nv)


def _embed_scores(query: str, contents: list[str]) -> Optional[list[float]]:
    """Return cosine scores via Lemonade embeddings, or None on failure."""
    if not contents:
        return []
    try:
        from llm.lemonade.embeddings import embed

        vectors = embed([query, *contents])
        if len(vectors) != 1 + len(contents):
            return None
        qv = vectors[0]
        return [_cosine(qv, vectors[i + 1]) for i in range(len(contents))]
    except Exception:
        return None


def score_memories(
    query: str,
    rows: list[dict[str, Any]],
    *,
    use_embeddings: bool = True,
) -> list[tuple[float, dict[str, Any]]]:
    """Score each memory row; higher is more relevant."""
    q_tok = _tokens(query)
    contents = [str(r.get("content") or "") for r in rows]
    emb = _embed_scores(query, contents) if use_embeddings else None
    scored: list[tuple[float, dict[str, Any]]] = []
    for i, row in enumerate(rows):
        content = contents[i]
        jac = _jaccard(q_tok, _tokens(content))
        # Soft keyword boost: any shared non-trivial token
        boost = 0.15 if (q_tok & _tokens(content)) else 0.0
        cos = emb[i] if emb is not None else 0.0
        # Blend: embeddings help, but weak cosine without lexical overlap
        # must not inject unrelated memories (e.g. weather vs colour).
        if emb is not None:
            lexical = jac > 0.0 or boost > 0.0
            # Strong embedding alone is rare for short prefs; require
            # lexical overlap unless cosine is very high.
            if lexical or cos >= 0.62:
                score = 0.65 * cos + 0.35 * max(jac, boost)
            else:
                score = 0.0
        else:
            score = max(jac, boost)
            # Prefer preference/fact rows slightly when query looks personal
            if any(
                k in query.lower()
                for k in ("favourite", "favorite", "prefer", "remember", "my ")
            ):
                if row.get("category") in {"preference", "fact"} and score > 0:
                    score += 0.05
        scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], -(x[1].get("id") or 0)))
    return scored


# Coding / workspace prompts must not pull unrelated memories into the
# system prompt (Round 3 coding_wordcount: 5 injected memories then first
# LLM call ReadTimeout at 176s).
_CODING_QUERY = re.compile(
    r"(?i)\b(?:ws_write|ws_edit|run_tests|run_file|pytest|wordcount|"
    r"python\s+function|module\s+\w+\.py|coding\s+workspace|"
    r"eval_\w+|write\s+a\s+python)\b"
)


def recall_relevant(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    threshold: float = DEFAULT_THRESHOLD,
    use_embeddings: bool = True,
    rows: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Return up to top_k memories above the similarity threshold."""
    if not (query or "").strip():
        return []
    # Skip auto-recall on coding-task prompts — they are not memory questions
    # and injected rows bloat the first LLM call into timeouts.
    if _CODING_QUERY.search(query):
        return []
    if rows is None:
        rows = list_memories(limit=200)
    if not rows:
        return []
    scored = score_memories(query, rows, use_embeddings=use_embeddings)
    hits = [row for score, row in scored if score >= threshold][:top_k]
    return hits


def format_memory_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = [MEMORY_HEADER]
    for row in rows:
        cat = row.get("category") or "memory"
        content = (row.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- ({cat}) {content}")
    if len(lines) == 1:
        return ""
    lines.append(MEMORY_FOOTER)
    return "\n".join(lines)
