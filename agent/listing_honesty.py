"""When the user asks for biggest/largest files, answer from list_directory only."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_BIGGEST_RE = re.compile(
    r"(?i)\b(biggest|largest|top\s+\d+\s+(?:biggest|largest|files)|"
    r"\d+\s+biggest|\d+\s+largest)\b"
)
_NAME_IN_BACKTICKS = re.compile(r"`([^`\n]{1,120})`")
_NAME_AS_PATH = re.compile(
    r"(?i)\b([a-z0-9_\-]+\.(?:zip|bin|exe|txt|dat|png|jpg|jpeg|gif|pdf|mp4|docx|js|log|tmp))\b"
)


def is_biggest_files_question(text: str) -> bool:
    return bool(_BIGGEST_RE.search(text or ""))


def _entries_from_tool_result(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [e for e in result if isinstance(e, dict) and e.get("name")]
    if isinstance(result, str):
        s = result.strip()
        if s.startswith("["):
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                return []
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict) and e.get("name")]
    return []


def last_size_sorted_listing(transcript: Any) -> list[dict[str, Any]]:
    """Return file entries from the latest list_directory tool_call, largest first."""
    from pathlib import Path

    if transcript is None:
        return []
    path = getattr(transcript, "path", None)
    if path is None:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except Exception:
        return []
    best: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "tool_call" or ev.get("name") != "list_directory":
            continue
        args = ev.get("args") or {}
        sort_by = str(args.get("sort_by") or "name").lower()
        entries = _entries_from_tool_result(ev.get("result"))
        files = [e for e in entries if (e.get("type") or "file") != "dir"]
        if not files:
            continue
        # Prefer size-sorted calls; still accept others and sort by size_bytes.
        if sort_by != "size":
            files = sorted(
                files,
                key=lambda e: int(e.get("size_bytes") or 0),
                reverse=True,
            )
        best = files
    return best


def names_claimed_in_answer(answer: str) -> set[str]:
    names: set[str] = set()
    for m in _NAME_IN_BACKTICKS.finditer(answer or ""):
        base = m.group(1).replace("\\", "/").split("/")[-1].strip()
        if "." in base:
            names.add(base.lower())
    for m in _NAME_AS_PATH.finditer(answer or ""):
        names.add(m.group(1).lower())
    return names


def format_top_listing(files: list[dict[str, Any]], *, n: int = 10) -> str:
    lines = [
        f"Here are the {min(n, len(files))} biggest files "
        f"(from list_directory, largest first):"
    ]
    for i, e in enumerate(files[:n], 1):
        name = e.get("name") or ""
        size = e.get("size") or e.get("size_bytes") or ""
        if size != "" and e.get("size"):
            lines.append(f"{i}. {name} — {e.get('size')}")
        elif size != "":
            lines.append(f"{i}. {name} — {size} bytes")
        else:
            lines.append(f"{i}. {name}")
    return "\n".join(lines)


def maybe_correct_biggest_files_answer(
    question: str,
    answer: str,
    transcript: Any = None,
    *,
    top_n: int = 10,
) -> tuple[str, Optional[dict[str, Any]]]:
    """If the answer invents file names, replace it with the tool listing."""
    if not is_biggest_files_question(question):
        return answer, None
    files = last_size_sorted_listing(transcript)
    if not files:
        return answer, None
    expected = {str(e.get("name") or "").lower() for e in files[:top_n] if e.get("name")}
    claimed = names_claimed_in_answer(answer)
    if not claimed:
        # No filenames at all — still prefer a concrete listing.
        fixed = format_top_listing(files, n=top_n)
        return fixed, {"corrected": True, "reason": "missing_names"}
    invented = {c for c in claimed if c not in {str(e.get("name") or "").lower() for e in files}}
    missing_top = expected - claimed
    # Hallucination: names not in the listing, or missing most of the real top-N.
    if invented or len(missing_top) >= max(3, top_n // 2):
        fixed = format_top_listing(files, n=top_n)
        return fixed, {
            "corrected": True,
            "invented": sorted(invented),
            "missing_top": sorted(missing_top),
        }
    return answer, None
