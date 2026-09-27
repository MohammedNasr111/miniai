"""LanceDB-backed vector storage for document chunks.

rebuild_index() wipes and recreates the whole table - used only for
the fixed test fixtures in scripts/ingest_documents.py.

add_documents() is the real incremental path: for each source_path
in the given records, it deletes only that path's existing rows
before inserting the new ones, leaving every other previously
indexed source untouched. This is what index_documents() (in
tools/knowledge/knowledge_tools.py) uses, so indexing a new folder
never erases content indexed from a different folder earlier.
"""

from pathlib import Path

import lancedb

from llm.lemonade.embeddings import embed

DB_PATH = Path(__file__).parent / "lancedb"
TABLE_NAME = "document_chunks"


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(DB_PATH))


def rebuild_index(records: list[dict]) -> int:
    """records: list of dicts with keys source_path, page_number
    (Optional[int]), chunk_index, content. Embeds all content and
    (re)creates the table from scratch. Returns the number of chunks
    indexed.
    """
    if not records:
        raise ValueError("No records to index")
    contents = [r["content"] for r in records]
    vectors = embed(contents)
    rows = [
        {
            "vector": vectors[i],
            "content": records[i]["content"],
            "source_path": records[i]["source_path"],
            "page_number": records[i]["page_number"] if records[i]["page_number"] is not None else -1,
            "chunk_index": records[i]["chunk_index"],
        }
        for i in range(len(records))
    ]
    db = get_db()
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")
    return len(rows)


def add_documents(records: list[dict]) -> int:
    """Incrementally indexes records without touching unrelated
    existing content. For each unique source_path in records,
    first deletes any existing rows for that exact path (so
    re-indexing a file replaces its old chunks rather than
    duplicating them), then inserts the new rows. Rows from every
    OTHER source_path are left untouched.
    """
    if not records:
        raise ValueError("No records to index")

    contents = [r["content"] for r in records]
    vectors = embed(contents)

    rows = [
        {
            "vector": vectors[i],
            "content": records[i]["content"],
            "source_path": records[i]["source_path"],
            "page_number": records[i]["page_number"] if records[i]["page_number"] is not None else -1,
            "chunk_index": records[i]["chunk_index"],
        }
        for i in range(len(records))
    ]

    db = get_db()
    if TABLE_NAME not in db.list_tables().tables:
        db.create_table(TABLE_NAME, data=rows)
        return len(rows)

    table = db.open_table(TABLE_NAME)
    unique_paths = {r["source_path"] for r in records}
    for path in unique_paths:
        escaped_path = path.replace("'", "''")
        table.delete(f"source_path = '{escaped_path}'")
    table.add(rows)
    return len(rows)


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    db = get_db()
    if TABLE_NAME not in db.list_tables().tables:
        return []
    table = db.open_table(TABLE_NAME)
    query_vector = embed(query)[0]
    results = (
        table.search(query_vector)
        .limit(top_k)
        .to_list()
    )
    return [
        {
            "content": r["content"],
            "source_path": r["source_path"],
            "page_number": r["page_number"] if r["page_number"] != -1 else None,
            "chunk_index": r["chunk_index"],
            "distance": r["_distance"],  # LOWER is more similar - this is a
                                         # distance metric, not a confidence
                                         # score. Do not sort/threshold as if
                                         # higher were better.
        }
        for r in results
    ]
