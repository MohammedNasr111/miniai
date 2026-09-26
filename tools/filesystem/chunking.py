"""Splits text into overlapping chunks for embedding. Character-based,
not token-based - simple and dependency-free; if chunk boundaries prove
too coarse once real retrieval is tested, a token-aware chunker is a
drop-in replacement later, not an architecture change.
"""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        if end == text_len:
            break
        start = end - overlap
    return chunks
