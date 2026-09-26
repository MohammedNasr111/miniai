"""Parses plain text and Markdown files. Both are just UTF-8 text -
no structure to extract beyond the raw content.
"""

from pathlib import Path


def parse_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")
