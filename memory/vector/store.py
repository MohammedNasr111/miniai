"""LanceDB-backed vector storage for document chunks.

rebuild_index() wipes and recreates the whole table - used only for
the fixed test fixtures in scripts/ingest_documents.py.

add_documents() is the real incremental path: for each source_path
in the given records, it deletes only that path's existing rows
before inserting the new ones, leaving every other previously
indexed source untouched. This is what index_documents() (in
tools/knowledge/knowledge_tools.py) uses, so indexing a new folder
never erases content indexed from a different folder earlier.

document_sources holds one fingerprint row per source file (sha256 of
the bytes on disk, mtime, and indexed_at). rebuild_index replaces that
table; add_documents replaces only the rows for paths it writes.
Pass db_path to point at a different database directory. The default
is DB_PATH.
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path

import lancedb
import pyarrow as pa

from llm.lemonade.embeddings import embed

DB_PATH = Path(__file__).parent / "lancedb"
TABLE_NAME = "document_chunks"
SOURCES_TABLE = "document_sources"

_SOURCES_SCHEMA = pa.schema([
    pa.field("source_path", pa.utf8()),
    pa.field("sha256", pa.utf8()),
    pa.field("mtime", pa.float64()),
    pa.field("indexed_at", pa.utf8()),
])


def get_db(db_path: str | Path | None = None):
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(path))


def _fingerprint_rows(source_paths: set[str]) -> list[dict]:
    """One row per source file, hashed from the bytes on disk now."""
    indexed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for source_path in sorted(source_paths):
        path = Path(source_path)
        data = path.read_bytes()
        rows.append({
            "source_path": source_path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "mtime": float(path.stat().st_mtime),
            "indexed_at": indexed_at,
        })
    return rows


def _write_fingerprints(db, rows: list[dict], *, replace_all: bool) -> None:
    if replace_all or SOURCES_TABLE not in db.list_tables().tables:
        db.create_table(SOURCES_TABLE, data=rows, schema=_SOURCES_SCHEMA, mode="overwrite")
        return
    table = db.open_table(SOURCES_TABLE)
    for row in rows:
        escaped_path = row["source_path"].replace("'", "''")
        table.delete(f"source_path = '{escaped_path}'")
    table.add(rows)


def _chunk_rows(records: list[dict], vectors: list) -> list[dict]:
    return [
        {
            "vector": vectors[i],
            "content": records[i]["content"],
            "source_path": records[i]["source_path"],
            "page_number": records[i]["page_number"] if records[i]["page_number"] is not None else -1,
            "chunk_index": records[i]["chunk_index"],
        }
        for i in range(len(records))
    ]


def rebuild_index(records: list[dict], *, db_path: str | Path | None = None) -> int:
    """records: list of dicts with keys source_path, page_number
    (Optional[int]), chunk_index, content. Embeds all content and
    (re)creates the table from scratch. Returns the number of chunks
    indexed. Also replaces the document_sources fingerprint table.
    """
    if not records:
        raise ValueError("No records to index")
    fingerprints = _fingerprint_rows({r["source_path"] for r in records})
    contents = [r["content"] for r in records]
    vectors = embed(contents)
    rows = _chunk_rows(records, vectors)
    db = get_db(db_path)
    db.create_table(TABLE_NAME, data=rows, mode="overwrite")
    _write_fingerprints(db, fingerprints, replace_all=True)
    return len(rows)


def add_documents(records: list[dict], *, db_path: str | Path | None = None) -> int:
    """Incrementally indexes records without touching unrelated
    existing content. For each unique source_path in records,
    first deletes any existing rows for that exact path (so
    re-indexing a file replaces its old chunks rather than
    duplicating them), then inserts the new rows. Rows from every
    OTHER source_path are left untouched. The fingerprint for each
    written source_path is replaced the same way.
    """
    if not records:
        raise ValueError("No records to index")

    source_paths = {r["source_path"] for r in records}
    fingerprints = _fingerprint_rows(source_paths)
    contents = [r["content"] for r in records]
    vectors = embed(contents)
    rows = _chunk_rows(records, vectors)

    db = get_db(db_path)
    if TABLE_NAME not in db.list_tables().tables:
        db.create_table(TABLE_NAME, data=rows)
        _write_fingerprints(db, fingerprints, replace_all=True)
        return len(rows)

    table = db.open_table(TABLE_NAME)
    for path in source_paths:
        escaped_path = path.replace("'", "''")
        table.delete(f"source_path = '{escaped_path}'")
    table.add(rows)
    _write_fingerprints(db, fingerprints, replace_all=False)
    return len(rows)


def _load_fingerprints(db) -> dict[str, dict]:
    if SOURCES_TABLE not in db.list_tables().tables:
        return {}
    table = db.open_table(SOURCES_TABLE)
    if table.count_rows() == 0:
        return {}
    return {row["source_path"]: row for row in table.to_arrow().to_pylist()}


def _freshness_for(source_path: str, row: dict | None) -> str:
    if not os.path.exists(source_path):
        return "file missing"
    if row is None:
        return "unknown (indexed before freshness tracking)"
    if os.path.getmtime(source_path) == float(row["mtime"]):
        return "current"
    digest = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
    if digest == row["sha256"]:
        return "current"
    return "modified since indexing"


def _freshness_by_path(db, source_paths: list[str]) -> dict[str, str]:
    """One freshness value per distinct path in this search."""
    stored = _load_fingerprints(db)
    freshness = {}
    for source_path in dict.fromkeys(source_paths):
        freshness[source_path] = _freshness_for(source_path, stored.get(source_path))
    return freshness


def search_knowledge(
    query: str,
    top_k: int = 5,
    *,
    db_path: str | Path | None = None,
) -> list[dict]:
    db = get_db(db_path)
    if TABLE_NAME not in db.list_tables().tables:
        return []
    table = db.open_table(TABLE_NAME)
    query_vector = embed(query)[0]
    results = (
        table.search(query_vector)
        .limit(top_k)
        .to_list()
    )
    found = [
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
    freshness = _freshness_by_path(db, [row["source_path"] for row in found])
    for row in found:
        row["freshness"] = freshness[row["source_path"]]
    return found
