"""Search, then fetch live pages and rank passages across them.

Not registered with the model. A later task wires this into the registry.
"""

import time
from dataclasses import dataclass
from typing import Optional

from llm.lemonade.embeddings import embed
from security.gate import Tier, check_permission
from tools.filesystem.chunking import chunk_text
from tools.web.fetch_tools import download, extract_text, validate_url
from tools.web.search.tavily import TavilyProvider
from tools.web.untrusted import (
    BEGIN_MARKER,
    END_MARKER,
    PREAMBLE,
    one_line,
    sanitize,
)

# The executor must taint the session when a web_research call succeeds.
# Registration happens in a later task.
UNTRUSTED = True

RESEARCH_DEADLINE_SECONDS = 90
SEARCH_COUNT = 6
MAX_CHUNKS_PER_PAGE = 60
EMBED_BATCH = 32
TOP_CHUNKS = 6
MAX_CHUNKS_PER_SOURCE = 3
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


@dataclass
class _Page:
    rank: int
    title: Optional[str]
    final_url: str
    chunks: list[str]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _safe(text: str) -> str:
    return one_line(sanitize(text))


def _short_reason(exc: ValueError) -> str:
    return _safe(str(exc))[:200]


def web_research(question: str, max_sources: int = 4) -> str:
    """Search, fetch up to max_sources pages, and return ranked passages."""
    check_permission(
        action="web_research",
        tier=Tier.AUTO_ALLOW,
        description=f"Web research: {question}",
    )
    if max_sources < 1:
        max_sources = 1
    elif max_sources > 4:
        max_sources = 4
    started = time.monotonic()
    results = TavilyProvider().search(question, SEARCH_COUNT)
    pages: list[_Page] = []
    skipped: list[str] = []
    for result in results:
        if len(pages) >= max_sources:
            break
        if time.monotonic() - started >= RESEARCH_DEADLINE_SECONDS:
            skipped.append("skipped: remaining results (time budget reached)")
            break
        try:
            validate_url(result.url)
            final_url, content_type, body = download(result.url)
            title, extracted = extract_text(body, content_type)
        except ValueError as exc:
            skipped.append(
                f"skipped: {_safe(result.url)} ({_short_reason(exc)})"
            )
            continue
        chunks = chunk_text(
            extracted, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP
        )[:MAX_CHUNKS_PER_PAGE]
        pages.append(
            _Page(
                rank=len(pages) + 1,
                title=title,
                final_url=final_url,
                chunks=chunks,
            )
        )
    chosen = _select(question, pages, expand_neighbors=True)
    return _render(question, pages, chosen, skipped)


def _select(
    question: str,
    pages: list[_Page],
    *,
    use_prefixes: bool = False,
    expand_neighbors: bool = False,
) -> list[tuple[float, _Page, int, str]]:
    """Top 6 chunks by similarity, at most 3 from any one page.

    Prefixes are applied only to the strings sent to the embedder.
    Neighbor expansion appends the next chunk's text after selection;
    the caps count selected chunks, not neighbors.
    """
    flat: list[tuple[_Page, int, str]] = []
    for page in pages:
        for index, chunk in enumerate(page.chunks):
            flat.append((page, index, chunk))
    if not flat:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(flat), EMBED_BATCH):
        batch = [
            _for_embed(chunk, use_prefixes)
            for _page, _index, chunk in flat[start:start + EMBED_BATCH]
        ]
        vectors.extend(embed(batch))
    if len(vectors) != len(flat):
        raise ValueError(
            f"Embedding service returned {len(vectors)} vectors for "
            f"{len(flat)} chunks"
        )
    query_vector = embed(_for_embed(question, use_prefixes, query=True))[0]
    scored = sorted(
        (
            (_dot(query_vector, vector), page, index, chunk)
            for (page, index, chunk), vector in zip(flat, vectors)
        ),
        key=lambda row: row[0],
        reverse=True,
    )
    chosen: list[tuple[float, _Page, int, str]] = []
    per_page: dict[int, int] = {}
    for score, page, index, chunk in scored:
        if per_page.get(page.rank, 0) >= MAX_CHUNKS_PER_SOURCE:
            continue
        chosen.append((score, page, index, chunk))
        per_page[page.rank] = per_page.get(page.rank, 0) + 1
        if len(chosen) >= TOP_CHUNKS:
            break
    chosen.sort(key=lambda row: (row[1].rank, row[2]))
    if not expand_neighbors:
        return chosen
    selected = {(page.rank, index) for _score, page, index, _chunk in chosen}
    expanded: list[tuple[float, _Page, int, str]] = []
    for score, page, index, chunk in chosen:
        neighbor = index + 1
        if neighbor < len(page.chunks) and (page.rank, neighbor) not in selected:
            chunk = chunk + "\n" + page.chunks[neighbor]
        expanded.append((score, page, index, chunk))
    return expanded


def _for_embed(text: str, use_prefixes: bool, query: bool = False) -> str:
    if not use_prefixes:
        return text
    if query:
        return "search_query: " + text
    return "search_document: " + text


def _render(
    question: str,
    pages: list[_Page],
    chosen: list[tuple[float, _Page, int, str]],
    skipped: list[str],
) -> str:
    lines = [
        *PREAMBLE,
        BEGIN_MARKER,
        f"Research question: {_safe(question)}",
    ]
    if not pages:
        lines.append("No pages could be fetched.")
    else:
        current: Optional[int] = None
        for score, page, index, chunk in chosen:
            if page.rank != current:
                title = _safe("" if page.title is None else page.title)[:200]
                lines.append(f"[source {page.rank}] Title: {title}")
                lines.append(f"URL: {_safe(page.final_url)}")
                current = page.rank
            lines.append(
                f"[source {page.rank}, chunk {index}, similarity {score:.3f}]"
            )
            lines.append(_safe(chunk))
    if skipped:
        lines.append("Skipped:")
        lines.extend(skipped)
    else:
        lines.append("Skipped: none")
    lines.append(END_MARKER)
    return "\n".join(lines)
