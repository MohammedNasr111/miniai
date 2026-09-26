"""SQLite-backed long-term memory storage.

Categories are deliberately narrow for now: fact, preference, project,
research. This is NOT the same as conversation history (short-term
context) - nothing here is written automatically. Something only lands
here when explicitly saved via save_memory().
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "miniai_memory.db"
VALID_CATEGORIES = {"fact", "preference", "project", "research"}


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_memory(content: str, category: str) -> int:
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
        )
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO memories (category, content, created_at) VALUES (?, ?, ?)",
        (category, content, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def _escape_like(query: str) -> str:
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_memory(query: str, category: Optional[str] = None) -> list[dict]:
    escaped = _escape_like(query)
    pattern = f"%{escaped}%"
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM memories WHERE content LIKE ? ESCAPE '\\' AND category = ? ORDER BY id DESC",
            (pattern, category),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memories WHERE content LIKE ? ESCAPE '\\' ORDER BY id DESC",
            (pattern,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def list_memories(category: Optional[str] = None, limit: int = 50) -> list[dict]:
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM memories WHERE category = ? ORDER BY id DESC LIMIT ?",
            (category, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]
