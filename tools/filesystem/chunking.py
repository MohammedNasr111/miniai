"""Splits text into overlapping chunks for embedding. Character-based,
not token-based - simple and dependency-free; if chunk boundaries prove
too coarse once real retrieval is tested, a token-aware chunker is a
drop-in replacement later, not an architecture change.

Markdown/pipe tables keep their header row with every chunk that contains
data rows (Stage 12b-pre2).
"""

from __future__ import annotations

import re

_SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _is_sep(line: str) -> bool:
    return bool(_SEP_RE.match(line.strip()))


def _is_row(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|") or s.count("|") < 2:
        return False
    return not _is_sep(s)


def _plain_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        if end == text_len:
            break
        start = end - overlap
    return chunks


def _table_chunks(
    header: str,
    sep: str,
    data_rows: list[str],
    chunk_size: int,
) -> list[str]:
    """Pack data rows; each chunk starts with header+sep (counts toward size)."""
    prefix = f"(table header repeated)\n{header}\n{sep}\n"
    # First chunk may omit the marker if we want header natural — still mark
    # for consistency when header is repeated. For the chunk that would
    # naturally include the original header at the start of the table, we
    # still use the same prefix for uniformity.
    budget = max(1, chunk_size - len(prefix))
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for row in data_rows:
        row_len = len(row) + (1 if buf else 0)
        if buf and buf_len + row_len > budget:
            chunks.append(prefix + "\n".join(buf))
            buf = [row]
            buf_len = len(row)
        else:
            if buf:
                buf_len += 1 + len(row)
            else:
                buf_len = len(row)
            buf.append(row)
    if buf:
        chunks.append(prefix + "\n".join(buf))
    return chunks


def _iter_blocks(lines: list[str]) -> list[tuple[str, object]]:
    """Yield ('plain', text) or ('table', (header, sep, data_rows))."""
    blocks: list[tuple[str, object]] = []
    i = 0
    plain: list[str] = []
    n = len(lines)

    def flush_plain() -> None:
        nonlocal plain
        if plain:
            blocks.append(("plain", "\n".join(plain)))
            plain = []

    while i < n:
        line = lines[i]
        # Table starts with a row followed by a separator.
        if (
            _is_row(line)
            and i + 1 < n
            and _is_sep(lines[i + 1])
        ):
            flush_plain()
            header = line.rstrip("\n")
            sep = lines[i + 1].rstrip("\n")
            i += 2
            data: list[str] = []
            while i < n and _is_row(lines[i]):
                data.append(lines[i].rstrip("\n"))
                i += 1
            blocks.append(("table", (header, sep, data)))
            continue
        plain.append(line.rstrip("\n"))
        i += 1
    flush_plain()
    return blocks


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    if not text:
        return []
    lines = text.splitlines()
    # Fast path: no pipe-table structure.
    if not any(_is_row(ln) and _is_sep(lines[i + 1]) for i, ln in enumerate(lines[:-1])):
        return _plain_chunks(text, chunk_size, overlap)

    chunks: list[str] = []
    for kind, payload in _iter_blocks(lines):
        if kind == "plain":
            body = str(payload)
            if not body.strip():
                continue
            chunks.extend(_plain_chunks(body, chunk_size, overlap))
        else:
            header, sep, data = payload  # type: ignore[misc]
            if not data:
                # Header-only table: keep as one small chunk.
                chunks.append(f"{header}\n{sep}")
            else:
                chunks.extend(_table_chunks(header, sep, data, chunk_size))
    return chunks
