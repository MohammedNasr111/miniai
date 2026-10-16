"""Fixture loader for Stage 5 tests: indexes sample.pdf and ARCHITECTURE.md.

Only ever writes to the store pointed at by VECTOR_DB_PATH (set by
tests.support.use_temp_data in test scripts). Running this module as
__main__ also forces a temporary store so it cannot wipe production data.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def build_records() -> list[dict]:
    from tools.filesystem.chunking import chunk_text
    from tools.filesystem.parsers.pdf_parser import parse_pdf
    from tools.filesystem.parsers.text_parser import parse_text

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


def load_fixture_index() -> int:
    """Rebuild the (temporary) vector index with the fixed fixtures."""
    from tests.support import assert_not_real_data
    from memory.vector.store import rebuild_index

    assert_not_real_data()
    records = build_records()
    return rebuild_index(records)


def main() -> None:
    from tests.support import use_temp_data

    use_temp_data()
    count = load_fixture_index()
    records = build_records()
    print(
        f"Indexed {count} chunks from "
        f"{len({r['source_path'] for r in records})} source documents "
        f"(temporary store only)."
    )


if __name__ == "__main__":
    main()
