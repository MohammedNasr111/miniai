"""Agent-facing memory tools. Wraps memory/database/db.py with the
permission gate, same pattern as tools/filesystem/fs_tools.py.
"""

from typing import Optional

from memory.database.db import VALID_CATEGORIES
from memory.database.db import list_memories as _list_memories
from memory.database.db import save_memory as _save_memory
from memory.database.db import search_memory as _search_memory
from security.gate import Tier, check_permission


def save_memory(content: str, category: str) -> str:
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
        )
    check_permission(
        action="save_memory",
        tier=Tier.CONFIRM,
        description=f"Save to long-term memory [{category}]: {content}",
    )
    row_id = _save_memory(content, category)
    return f"Saved memory #{row_id} in category '{category}'."


def search_memory(query: str, category: Optional[str] = None) -> list[dict]:
    check_permission(
        action="search_memory",
        tier=Tier.AUTO_ALLOW,
        description=f"Search memory for: {query}" + (f" in category {category}" if category else ""),
    )
    return _search_memory(query, category)


def list_memories(category: Optional[str] = None) -> list[dict]:
    check_permission(
        action="list_memories",
        tier=Tier.AUTO_ALLOW,
        description=f"List memories" + (f" in category {category}" if category else " (all categories)"),
    )
    return _list_memories(category)
