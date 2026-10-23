"""Agent-facing knowledge-base tools: indexing folders into the vector
store and searching it. Same permission-gate pattern as fs_tools.py
and memory_tools.py.
"""

import os

from memory.vector.store import add_documents
from memory.vector.store import search_knowledge as _search_knowledge
from security.gate import Tier, check_permission
from tools.filesystem.chunking import chunk_text
from tools.filesystem.parsers.pdf_parser import parse_pdf
from tools.filesystem.parsers.text_parser import parse_text

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}


def _find_supported_files(folder_path: str) -> list[str]:
    found = []
    for dirpath, dirnames, filenames in os.walk(folder_path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
                found.append(os.path.join(dirpath, name))
    return found


def index_documents(folder_path: str) -> str:
    files = _find_supported_files(folder_path)

    check_permission(
        action="index_documents",
        tier=Tier.CONFIRM,
        description=(
            f"Index documents under: {folder_path}\n"
            f"Found {len(files)} supported file(s) "
            f"({', '.join(sorted(SUPPORTED_EXTENSIONS))}) to add to the "
            f"local knowledge base."
        ),
    )

    if not files:
        return f"No supported files found under {folder_path}. Nothing indexed."

    records = []
    for file_path in files:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            for page_number, page_text in parse_pdf(file_path):
                for i, chunk in enumerate(chunk_text(page_text, chunk_size=500, overlap=50)):
                    records.append({
                        "source_path": file_path,
                        "page_number": page_number,
                        "chunk_index": i,
                        "content": chunk,
                    })
        else:
            text = parse_text(file_path)
            for i, chunk in enumerate(chunk_text(text, chunk_size=500, overlap=50)):
                records.append({
                    "source_path": file_path,
                    "page_number": None,
                    "chunk_index": i,
                    "content": chunk,
                })

    count = add_documents(records)
    return f"Indexed {count} chunks from {len(files)} file(s) under {folder_path}."


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    check_permission(
        action="search_knowledge",
        tier=Tier.AUTO_ALLOW,
        description=f"Search local knowledge base for: {query}",
    )
    hits = _search_knowledge(query, top_k)
    from tools.filesystem.untrusted_file import maybe_wrap_outside_file

    wrapped: list[dict] = []
    for hit in hits:
        row = dict(hit)
        src = row.get("source_path") or ""
        content = row.get("content")
        if isinstance(content, str) and src:
            row["content"] = maybe_wrap_outside_file(src, content)
        wrapped.append(row)
    return wrapped
