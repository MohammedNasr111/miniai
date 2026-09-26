"""Standalone tests for text parsing, PDF parsing, and chunking - no
LLM, no LanceDB, no permission gate involved. Just the primitives.
"""

from pathlib import Path

from tools.filesystem.chunking import chunk_text
from tools.filesystem.parsers.pdf_parser import parse_pdf
from tools.filesystem.parsers.text_parser import parse_text

PROJECT_ROOT = Path(__file__).parent.parent


def test_text_parser() -> None:
    content = parse_text(str(PROJECT_ROOT / "ARCHITECTURE.md"))
    assert len(content) > 0, "ARCHITECTURE.md parsed as empty"
    assert "MiniAI" in content, "Expected content not found"
    print(f"text_parser: PASS ({len(content)} characters read)")


def test_pdf_parser() -> None:
    pages = parse_pdf(str(PROJECT_ROOT / "tests" / "fixtures" / "sample.pdf"))
    assert len(pages) == 2, f"Expected 2 pages, got {len(pages)}"
    page_num_1, text_1 = pages[0]
    page_num_2, text_2 = pages[1]
    assert page_num_1 == 1 and "PAGE ONE MARKER" in text_1, "Page 1 content/number mismatch"
    assert page_num_2 == 2 and "PAGE TWO MARKER" in text_2, "Page 2 content/number mismatch"
    assert "PAGE TWO MARKER" not in text_1, "Page 2 content leaked into page 1"
    print(f"pdf_parser: PASS (2 pages, correct markers on correct pages)")


def test_chunking() -> None:
    text = "".join(f"{i:04d}-" for i in range(500))  # long, deterministic string
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert all(len(c) <= 100 for c in chunks), "A chunk exceeded chunk_size"
    assert len(chunks) > 1, "Text should have produced multiple chunks"
    for i in range(len(chunks) - 1):
        end_of_current = chunks[i][-20:]
        start_of_next = chunks[i + 1][:20]
        assert end_of_current == start_of_next, f"Overlap mismatch at chunk {i}"
    reconstructed_start = chunks[0][:20]
    assert text.startswith(reconstructed_start), "First chunk doesn't match text start"
    print(f"chunking: PASS ({len(chunks)} chunks, overlap verified between all adjacent pairs)")


if __name__ == "__main__":
    test_text_parser()
    test_pdf_parser()
    test_chunking()
    print("\nAll parser/chunking tests passed.")
