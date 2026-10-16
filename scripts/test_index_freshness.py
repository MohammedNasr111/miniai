"""Freshness tracking for the knowledge index. Uses a temporary database
directory and a temporary source folder. Never opens memory/vector/lancedb
except to record that it was not modified.
"""

import os
import tempfile
import time
from pathlib import Path

from memory.vector.store import DB_PATH
from memory.vector.store import SOURCES_TABLE
from memory.vector.store import add_documents
from memory.vector.store import get_db
from memory.vector.store import search_knowledge
from tools.filesystem.chunking import chunk_text

REAL_DB = DB_PATH


def _snapshot(root: Path) -> tuple:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            st = path.stat()
            files.append((str(path.relative_to(root)), st.st_mtime_ns, st.st_size))
    return (root.stat().st_mtime_ns, tuple(files))


def _records(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    return [
        {
            "source_path": str(path),
            "page_number": None,
            "chunk_index": i,
            "content": chunk,
        }
        for i, chunk in enumerate(chunks)
    ]


def _freshness(db_path: Path, query: str, source: Path) -> str:
    results = search_knowledge(query, top_k=10, db_path=db_path)
    matched = [r for r in results if r["source_path"] == str(source)]
    assert matched, f"No chunk returned for {source.name}. Results: {results!r}"
    values = {r["freshness"] for r in matched}
    assert len(values) == 1, values
    return values.pop()


def _stored_mtime(db_path: Path, source: Path) -> float:
    table = get_db(db_path).open_table(SOURCES_TABLE)
    rows = [
        row for row in table.to_arrow().to_pylist()
        if row["source_path"] == str(source)
    ]
    assert len(rows) == 1, rows
    return float(rows[0]["mtime"])


def _fingerprint_count(db_path: Path, source: Path) -> int:
    table = get_db(db_path).open_table(SOURCES_TABLE)
    return sum(
        1 for row in table.to_arrow().to_pylist()
        if row["source_path"] == str(source)
    )


def _rewrite_same_bytes(path: Path) -> None:
    data = path.read_bytes()
    before = path.stat().st_mtime
    time.sleep(0.05)
    path.write_bytes(data)
    if path.stat().st_mtime == before:
        os.utime(path, (before + 2, before + 2))
    assert path.stat().st_mtime != before


def main() -> None:
    before = _snapshot(REAL_DB)
    print(f"Real DB mtime_ns before: {before[0]}")
    print(f"Real DB files before ({len(before[1])}):")
    for item in before[1]:
        print(f"  {item[0]}  mtime_ns={item[1]}  size={item[2]}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        db_path = root / "lancedb"
        src = root / "sources"
        src.mkdir()
        alpha = (src / "alpha.txt").resolve()
        beta = (src / "beta.txt").resolve()
        alpha.write_text(
            "Alpha note: the violet locomotive crossed the marble bridge at dawn.",
            encoding="utf-8",
        )
        beta.write_text(
            "Beta note: a copper kettle whistled beside the quiet greenhouse.",
            encoding="utf-8",
        )
        add_documents(_records(alpha) + _records(beta), db_path=db_path)

        alpha_q = "violet locomotive marble bridge"
        beta_q = "copper kettle quiet greenhouse"
        a1 = _freshness(db_path, alpha_q, alpha)
        b1 = _freshness(db_path, beta_q, beta)
        assert a1 == "current" and b1 == "current", (a1, b1)
        print(f"PASS: 1 - alpha={a1} beta={b1}")

        alpha.write_text(
            "Alpha note: the violet locomotive was repainted orange overnight.",
            encoding="utf-8",
        )
        a2 = _freshness(db_path, alpha_q, alpha)
        b2 = _freshness(db_path, beta_q, beta)
        assert a2 == "modified since indexing", a2
        assert b2 == "current", b2
        print(f"PASS: 2 - alpha={a2} beta={b2}")

        _rewrite_same_bytes(beta)
        stored = _stored_mtime(db_path, beta)
        assert os.path.getmtime(beta) != stored, (os.path.getmtime(beta), stored)
        b3 = _freshness(db_path, beta_q, beta)
        assert b3 == "current", b3
        print(f"PASS: 3 - beta={b3} (mtime changed, bytes identical)")

        alpha.unlink()
        a4 = _freshness(db_path, alpha_q, alpha)
        assert a4 == "file missing", a4
        print(f"PASS: 4 - alpha={a4}")

        escaped = str(beta).replace("'", "''")
        get_db(db_path).open_table(SOURCES_TABLE).delete(
            f"source_path = '{escaped}'"
        )
        assert _fingerprint_count(db_path, beta) == 0
        b5 = _freshness(db_path, beta_q, beta)
        assert b5 == "unknown (indexed before freshness tracking)", b5
        print(f"PASS: 5 - beta={b5}")

        beta.write_text(
            "Beta note: a copper kettle whistled beside a rebuilt greenhouse.",
            encoding="utf-8",
        )
        add_documents(_records(beta), db_path=db_path)
        b6 = _freshness(db_path, beta_q, beta)
        count = _fingerprint_count(db_path, beta)
        assert b6 == "current", b6
        assert count == 1, count
        print(f"PASS: 6 - beta={b6} fingerprint_rows={count}")

    after = _snapshot(REAL_DB)
    print(f"Real DB mtime_ns after: {after[0]}")
    print(f"Real DB files after ({len(after[1])}):")
    for item in after[1]:
        print(f"  {item[0]}  mtime_ns={item[1]}  size={item[2]}")
    assert before == after, "real database was touched"
    print("PASS: 7 - real database listing and mtime unchanged")
    print("All index-freshness checks passed.")


if __name__ == "__main__":
    main()
