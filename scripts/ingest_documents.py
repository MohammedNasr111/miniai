"""Ingests a fixed set of documents for Stage 5 testing: the two-page
PDF fixture and ARCHITECTURE.md. A general "point this at any folder"
ingestion tool comes later - this proves the pipeline end to end on
known content first.
"""

from pathlib import Path

from memory.vector.store import rebuild_index
from tools.filesystem.chunking import chunk_text
from tools.filesystem.parsers.pdf_parser import parse_pdf
from tools.filesystem.parsers.text_parser import parse_text

PROJECT_ROOT = Path(__file__).parent.parent


def build_records() -> list[dict]:
    records = []
    pdf_path = str(PROJECT_ROOT / "tests" / "fixtures" / "sample.pdf")
    for page_number, page_text in parse_pdf(pdf_path):
        for i, chunk in enumerate(chunk_text(page_text, chunk_size=500, overlap=50)):
            records.append({
                "source_path": pdf_path,
                "page_number": page_number,
                "chunk_index": i,
                "content": chunk,
            })
    md_path = str(PROJECT_ROOT / "ARCHITECTURE.md")
    md_text = parse_text(md_path)
    for i, chunk in enumerate(chunk_text(md_text, chunk_size=500, overlap=50)):
        records.append({
            "source_path": md_path,
            "page_number": None,
            "chunk_index": i,
            "content": chunk,
        })
    return records


def main() -> None:
    records = build_records()
    count = rebuild_index(records)
    print(f"Indexed {count} chunks from {len({r['source_path'] for r in records})} source documents.")


if __name__ == "__main__":
    main()
