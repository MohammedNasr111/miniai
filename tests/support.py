"""Test helpers: isolate every write from the real memory and vector stores.

Call use_temp_data() at the very top of a test script, BEFORE importing any
project module that reads config/settings (or memory/vector code). That sets
MINIAI_MEMORY_DB and MINIAI_VECTOR_DB to paths under a fresh temp directory.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_MEMORY_DB = (PROJECT_ROOT / "memory" / "database" / "miniai_memory.db").resolve()
REAL_VECTOR_DB = (PROJECT_ROOT / "memory" / "vector" / "lancedb").resolve()


def use_temp_data() -> Path:
    """Create a temp dir, point both store env vars at it, return the dir.

    Must run before `config.settings` (or anything that imports it) is loaded.
    """
    root = Path(tempfile.mkdtemp(prefix="miniai_test_"))
    memory_path = root / "miniai_memory.db"
    vector_path = root / "lancedb"
    os.environ["MINIAI_MEMORY_DB"] = str(memory_path)
    os.environ["MINIAI_VECTOR_DB"] = str(vector_path)
    print(f"[tests.support] temp data root={root}")
    print(f"[tests.support] MINIAI_MEMORY_DB={memory_path}")
    print(f"[tests.support] MINIAI_VECTOR_DB={vector_path}")
    return root


def assert_not_real_data() -> None:
    """Raise if either effective store path is the real production location."""
    # Import here so callers can set env via use_temp_data() first.
    from config import settings

    memory = Path(settings.MEMORY_DB_PATH).resolve()
    vector = Path(settings.VECTOR_DB_PATH).resolve()
    if memory == REAL_MEMORY_DB:
        raise RuntimeError(
            f"Refusing to run: MEMORY_DB_PATH resolves to the real store "
            f"({REAL_MEMORY_DB}). Call use_temp_data() before importing "
            f"project modules."
        )
    if vector == REAL_VECTOR_DB:
        raise RuntimeError(
            f"Refusing to run: VECTOR_DB_PATH resolves to the real store "
            f"({REAL_VECTOR_DB}). Call use_temp_data() before importing "
            f"project modules."
        )
