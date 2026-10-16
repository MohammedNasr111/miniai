"""Proves index_documents adds new content WITHOUT erasing previously
indexed content from a different folder - the specific regression this
task exists to prevent. No LLM involved.

Uses a temporary vector store: load_fixture_index() then index_documents.
"""

from pathlib import Path

from tests.support import assert_not_real_data, use_temp_data

use_temp_data()

from scripts.ingest_documents import load_fixture_index
from tools.knowledge.knowledge_tools import index_documents, search_knowledge

PROJECT_ROOT = Path(__file__).parent.parent


def main() -> None:
    assert_not_real_data()
    count = load_fixture_index()
    print(f"Fixture index loaded: {count} chunks (temporary store).")

    print("=== Step 1: index the new test folder (SHOULD prompt - answer yes) ===")
    result = index_documents(str(PROJECT_ROOT / "tests" / "fixtures" / "knowledge_folder"))
    print(result)

    print("\n=== Step 2: confirm the NEW content is findable ===")
    results = search_knowledge("purple caterpillar bicycle", top_k=3)
    assert results, "New content not found after indexing"
    assert "knowledge_folder" in results[0]["source_path"]
    print(f"PASS: found new content, source={results[0]['source_path']}")

    print("\n=== Step 3: confirm OLD content (from fixture loader) still exists ===")
    results = search_knowledge("which part of a cell produces energy", top_k=3)
    assert results, "Previously indexed PDF content is GONE - regression!"
    assert "sample.pdf" in results[0]["source_path"]
    print(f"PASS: old content survived, source={results[0]['source_path']}, page={results[0]['page_number']}")

    print("\n=== Step 4: re-index the SAME folder again (SHOULD prompt again - answer yes) - confirm no duplication ===")
    index_documents(str(PROJECT_ROOT / "tests" / "fixtures" / "knowledge_folder"))
    results = search_knowledge("purple caterpillar bicycle", top_k=10)
    matching_rows = [r for r in results if "knowledge_folder" in r["source_path"]]
    print(f"Rows from knowledge_folder after re-indexing twice: {len(matching_rows)} (should be 1, not 2)")


if __name__ == "__main__":
    main()
