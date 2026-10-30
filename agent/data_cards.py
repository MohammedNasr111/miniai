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
_last_card_this_turn: Optional[dict[str, Any]] = None


def reset_listing_card_turn() -> None:
    global _card_shown_this_turn, _last_card_this_turn
    _card_shown_this_turn = False
    _last_card_this_turn = None


def note_listing_card_shown(card: Optional[dict[str, Any]] = None) -> None:
    global _card_shown_this_turn, _last_card_this_turn
    _card_shown_this_turn = True
    if card is not None:
        _last_card_this_turn = card


def listing_card_shown_this_turn() -> bool:
    return bool(_card_shown_this_turn)


def last_listing_card_this_turn() -> Optional[dict[str, Any]]:
    return _last_card_this_turn


def _card_name_set(card: dict[str, Any]) -> set[str]:
    from agent.listing_honesty import normalize_listing_name

    names: set[str] = set()
    for key in ("rows", "all_rows"):
        rows = card.get(key) or []
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict) and r.get("name"):
                names.add(normalize_listing_name(str(r["name"])))
    return names


def _line_listing_name(line: str) -> Optional[str]:
    from agent.listing_honesty import normalize_listing_name

    m = re.match(r"^\s*(?:\d+[\.\)]\s*|[-*•]\s+)(.+?)\s*$", line or "")
    if not m:
        return None
    body = m.group(1).strip()
    bt = re.search(r"`([^`\n]{1,120})`", body)
    if bt:
        return normalize_listing_name(bt.group(1).replace("\\", "/").split("/")[-1])
    return normalize_listing_name(body)


def strip_card_relist_from_answer(
    answer: str,
    card: Optional[dict[str, Any]] = None,
) -> tuple[str, Optional[dict[str, Any]]]:
    """Drop consecutive list lines that only restate the data card rows.

    Keeps the sentence before the list. If nothing meaningful remains, builds a
    short sentence from the card's top rows.
    """
    card = card if card is not None else _last_card_this_turn
    if not card or not listing_card_shown_this_turn():
        return answer, None
    card_names = _card_name_set(card)
    if not card_names:
        return answer, None

    lines = (answer or "").splitlines()
    # Find runs of ≥3 consecutive list lines whose names are all on the card.
    i = 0
    strip_ranges: list[tuple[int, int]] = []
    while i < len(lines):
        name = _line_listing_name(lines[i])
        if name is None or name not in card_names:
            i += 1
            continue
        j = i
        while j < len(lines):
            n2 = _line_listing_name(lines[j])
            if n2 is None or n2 not in card_names:
                break
            j += 1
        if j - i >= 3:
            strip_ranges.append((i, j))
        i = max(j, i + 1)

    if not strip_ranges:
        return answer, None

    drop: set[int] = set()
    for a, b in strip_ranges:
        drop.update(range(a, b))
    kept = [ln for idx, ln in enumerate(lines) if idx not in drop]
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Meaningful leftover: any non-empty non-list prose, or shorter list.
    meaningful = False
    for ln in kept:
        if not ln.strip():
            continue
        if _line_listing_name(ln) is None:
            meaningful = True
            break
    meta = {
        "stripped_relist": True,
        "removed_lines": len(drop),
    }
    if meaningful and text:
        return text, meta

    rows = list(card.get("rows") or [])
    n = len(rows) or int(card.get("shown") or 3)
    names = [str(r.get("name") or "") for r in rows[:n] if r.get("name")]
    if not names:
        return text or answer, meta
    top = names[0]
    size = ""
    if rows and rows[0].get("size"):
        size = f" at {rows[0].get('size')}"
    if len(names) == 1:
        names_join = names[0]
    elif len(names) == 2:
        names_join = f"{names[0]} and {names[1]}"
    else:
        names_join = ", ".join(names[:-1]) + f", and {names[-1]}"
    fallback = (
        f"The {n} biggest are shown above — {top} is the largest{size}."
        if card.get("sort") == "size"
        else f"The listing above shows {names_join}."
    )
    # Prefer any leading sentence still present.
    if text and _line_listing_name(text.splitlines()[0]) is None:
        return (text.rstrip() + " " + fallback).strip(), meta
    return fallback, meta


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
