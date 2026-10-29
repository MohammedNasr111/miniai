"""Data cards: UI tables built from list_directory / search_files results."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from agent.listing_honesty import requested_listing_n

CARD_PROMPT_SENTENCE = (
    "The listing is already shown to the user as a table; do not re-list the "
    "rows — answer in at most two sentences, naming only the items that answer "
    "the question."
)

_NEWEST_RE = re.compile(
    r"(?i)\b(newest|most\s+recent|latest|recent(?:ly)?\s+modified|by\s+date)\b"
)
_BIGGEST_RE = re.compile(r"(?i)\b(biggest|largest|size)\b")

_card_shown_this_turn = False


def reset_listing_card_turn() -> None:
    global _card_shown_this_turn
    _card_shown_this_turn = False


def note_listing_card_shown() -> None:
    global _card_shown_this_turn
    _card_shown_this_turn = True


def listing_card_shown_this_turn() -> bool:
    return bool(_card_shown_this_turn)


def sort_mode_for_question(question: str) -> str:
    text = question or ""
    if _BIGGEST_RE.search(text):
        return "size"
    if _NEWEST_RE.search(text):
        return "modified"
    return "name"


def _parse_list_directory_result(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [e for e in result if isinstance(e, dict)]
    if isinstance(result, str):
        s = result.strip()
        if s.startswith("["):
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                return []
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
    return []


def _parse_search_files_result(result: Any) -> list[dict[str, Any]]:
    paths: list[str] = []
    if isinstance(result, list):
        paths = [str(p) for p in result if p]
    elif isinstance(result, str):
        s = result.strip()
        if s.startswith("["):
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, list):
                paths = [str(p) for p in data if p]
            else:
                paths = [ln.strip() for ln in s.splitlines() if ln.strip()]
        else:
            paths = [ln.strip() for ln in s.splitlines() if ln.strip()]
    rows: list[dict[str, Any]] = []
    for p in paths:
        name = p.replace("\\", "/").rstrip("/").split("/")[-1] or p
        rows.append({"name": name, "path": p, "size": "", "modified": ""})
    return rows


def _sort_rows(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "size":

        def _sz(e: dict[str, Any]) -> int:
            v = e.get("size_bytes")
            if v is None:
                return -1
            try:
                return int(v)
            except (TypeError, ValueError):
                return -1

        return sorted(rows, key=_sz, reverse=True)
    if mode == "modified":
        # Prefer ISO-like or local display strings; empty last.
        return sorted(
            rows,
            key=lambda e: str(e.get("modified") or ""),
            reverse=True,
        )
    return sorted(rows, key=lambda e: str(e.get("name") or "").lower())


def build_data_card(
    tool: str,
    result: Any,
    *,
    question: str = "",
    args: Optional[dict[str, Any]] = None,
    default_n: int = 20,
) -> Optional[dict[str, Any]]:
    """Return a UI data-card dict, or None if the tool/result is not listable."""
    args = args or {}
    tool = (tool or "").strip()
    if tool == "list_directory":
        rows = _parse_list_directory_result(result)
        if not rows:
            return None
        mode = sort_mode_for_question(question)
        # Honour explicit tool sort when the question didn't ask for size/date.
        tool_sort = str(args.get("sort_by") or "").lower()
        if mode == "name" and tool_sort in ("size", "modified", "name"):
            mode = tool_sort
        rows = _sort_rows(rows, mode)
        n = requested_listing_n(question, default=default_n)
        shown = rows[:n]
        return {
            "kind": "data_card",
            "tool": tool,
            "title": "Folder listing",
            "columns": ["name", "size", "modified"],
            "rows": [
                {
                    "name": str(e.get("name") or ""),
                    "size": str(e.get("size") or ("" if e.get("type") == "dir" else "")),
                    "modified": str(e.get("modified") or ""),
                    "type": str(e.get("type") or "file"),
                }
                for e in shown
            ],
            "total": len(rows),
            "shown": len(shown),
            "limit": n,
            "sort": mode,
            "path": str(args.get("path") or ""),
            "show_all": len(rows) > len(shown),
            "all_rows": [
                {
                    "name": str(e.get("name") or ""),
                    "size": str(e.get("size") or ""),
                    "modified": str(e.get("modified") or ""),
                    "type": str(e.get("type") or "file"),
                }
                for e in rows
            ]
            if len(rows) > len(shown)
            else None,
        }
    if tool == "search_files":
        rows = _parse_search_files_result(result)
        if not rows:
            return None
        n = requested_listing_n(question, default=default_n)
        shown = rows[:n]
        return {
            "kind": "data_card",
            "tool": tool,
            "title": "Search results",
            "columns": ["name", "path"],
            "rows": shown,
            "total": len(rows),
            "shown": len(shown),
            "limit": n,
            "sort": "name",
            "path": str(args.get("root") or args.get("path") or ""),
            "show_all": len(rows) > len(shown),
            "all_rows": rows if len(rows) > len(shown) else None,
        }
    return None
