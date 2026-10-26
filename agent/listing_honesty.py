"""Answers that name files/folders from list_directory must match the listing."""

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
# Folder-style names in backticks or bold (no extension required).
_FOLDERISH = re.compile(
    r"(?i)(?:`([^`\n]{1,120})`|\*\*([^*\n]{1,120})\*\*)"
)
_REMOVED_NOTE = "⚠ Removed {n} name(s) that weren't in the folder listing."


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


def last_list_directory_entries(transcript: Any) -> list[dict[str, Any]]:
    """Return entries from the latest list_directory tool_call."""
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
        entries = _entries_from_tool_result(ev.get("result"))
        if entries:
            best = entries
    return best


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
        if sort_by != "size":
            files = sorted(
                files,
                key=lambda e: int(e.get("size_bytes") or 0),
                reverse=True,
            )
        best = files
    return best


def listing_used_this_turn(transcript: Any) -> bool:
    return bool(last_list_directory_entries(transcript))


def names_in_listing(entries: list[dict[str, Any]]) -> set[str]:
    return {
        str(e.get("name") or "").lower()
        for e in entries
        if e.get("name")
    }


def names_claimed_in_answer(answer: str) -> set[str]:
    """File/folder names the answer presents as being in the listed folder."""
    names: set[str] = set()
    for m in _NAME_IN_BACKTICKS.finditer(answer or ""):
        base = m.group(1).replace("\\", "/").split("/")[-1].strip()
        if base:
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


def _strip_unknown_names(answer: str, known: set[str]) -> tuple[str, list[str]]:
    """Remove backtick / extension-looking names not in known; return (text, removed)."""
    removed: list[str] = []
    text = answer or ""

    def _bt(m: re.Match[str]) -> str:
        raw = m.group(1)
        base = raw.replace("\\", "/").split("/")[-1].strip()
        if not base:
            return m.group(0)
        if base.lower() in known:
            return m.group(0)
        # Only strip when it looks like a file/folder name claim
        # (has extension, or no spaces / short token).
        if "." in base or (" " not in base and len(base) <= 80):
            removed.append(base)
            return ""
        return m.group(0)

    text = _NAME_IN_BACKTICKS.sub(_bt, text)

    def _ext(m: re.Match[str]) -> str:
        name = m.group(1)
        if name.lower() in known:
            return m.group(0)
        removed.append(name)
        return ""

    text = _NAME_AS_PATH.sub(_ext, text)
    # Clean leftover empty list lines / double spaces
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # Drop orphaned numbered empties like "4. " or "4."
        if re.match(r"^\d+\.\s*$", stripped):
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, removed


def maybe_correct_listing_answer(
    question: str,
    answer: str,
    transcript: Any = None,
    *,
    top_n: int = 10,
) -> tuple[str, Optional[dict[str, Any]]]:
    """General rule: names presented as in the folder must appear in list_directory.

    Biggest-files questions still get a full rewrite from the size-sorted listing
    when names are invented or the top-N is mostly missing.
    """
    entries = last_list_directory_entries(transcript)
    if not entries:
        return answer, None

    known = names_in_listing(entries)

    # Special case: biggest/largest → prefer size-sorted rewrite when needed.
    if is_biggest_files_question(question):
        files = last_size_sorted_listing(transcript)
        if files:
            expected = {
                str(e.get("name") or "").lower()
                for e in files[:top_n]
                if e.get("name")
            }
            claimed = names_claimed_in_answer(answer)
            if not claimed:
                fixed = format_top_listing(files, n=top_n)
                return fixed, {"corrected": True, "reason": "missing_names"}
            invented = {c for c in claimed if c not in names_in_listing(files)}
            missing_top = expected - claimed
            if invented or len(missing_top) >= max(3, top_n // 2):
                fixed = format_top_listing(files, n=top_n)
                return fixed, {
                    "corrected": True,
                    "invented": sorted(invented),
                    "missing_top": sorted(missing_top),
                    "reason": "biggest_rewrite",
                }

    claimed = names_claimed_in_answer(answer)
    if not claimed:
        return answer, None
    invented = sorted(c for c in claimed if c not in known)
    if not invented:
        return answer, None
    cleaned, removed = _strip_unknown_names(answer, known)
    # Ensure we count every invented name we intended to remove.
    n = len(removed) or len(invented)
    note = _REMOVED_NOTE.format(n=n)
    if note not in cleaned:
        cleaned = (cleaned.rstrip() + "\n\n" + note).strip()
    return cleaned, {
        "corrected": True,
        "removed": removed or invented,
        "reason": "unknown_names",
    }


def maybe_correct_biggest_files_answer(
    question: str,
    answer: str,
    transcript: Any = None,
    *,
    top_n: int = 10,
) -> tuple[str, Optional[dict[str, Any]]]:
    """Back-compat alias — general listing honesty covers biggest-files too."""
    return maybe_correct_listing_answer(
        question, answer, transcript=transcript, top_n=top_n
    )
