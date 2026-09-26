"""Proves search_knowledge does real semantic retrieval with correct
citations - queries deliberately avoid the exact wording in the source
documents, so a pass can't be explained by substring luck.
"""

from memory.vector.store import search_knowledge


def check(query: str, expected_source_contains: str, expected_page) -> None:
    results = search_knowledge(query, top_k=3)
    assert results, f"No results for: {query}"
    top = results[0]
    print(f"\nQuery: {query!r}")
    print(f"  Top match source: {top['source_path']}")
    print(f"  Top match page:   {top['page_number']}")
    print(f"  Top match distance: {top['distance']:.4f}")
    print(f"  Top match content (first 100 chars): {top['content'][:100]!r}")
    assert expected_source_contains in top["source_path"], (
        f"Expected source containing '{expected_source_contains}', got '{top['source_path']}'"
    )
    assert top["page_number"] == expected_page, (
        f"Expected page {expected_page}, got {top['page_number']}"
    )
    print("  PASS")


def main() -> None:
    # Paraphrased, not copied verbatim from "mitochondria is the powerhouse
    # of the cell" - proves semantic match, not substring luck.
    check(
        "which part of a cell produces energy",
        expected_source_contains="sample.pdf",
        expected_page=1,
    )
    # Paraphrased, not copied verbatim from "should ask permission before
    # deleting files."
    check(
        "an AI agent should get user approval before removing files",
        expected_source_contains="sample.pdf",
        expected_page=2,
    )
    # Should retrieve from the markdown doc, not the PDF, and page_number
    # should be None since markdown has no pages.
    check(
        "what local model does this project use by default",
        expected_source_contains="ARCHITECTURE.md",
        expected_page=None,
    )
    print("\nAll search_knowledge tests passed.")


if __name__ == "__main__":
    main()
