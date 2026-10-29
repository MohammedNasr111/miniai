"""Answers that name files/folders from list_directory must match the listing.

Only listings from the *current* user turn count. Names the user asked to
create/write are never stripped. Only names presented as inside the listed
folder are checked.
"""

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

# "Create a file called test-note.txt …" / "make a folder named Foo" / etc.
_CREATE_NAME_RE = re.compile(
    r"(?:create|make|write|new|save|add)\s+(?:a\s+|an\s+)?"
    r"(?:file|folder|directory|note|document)?\s*"
    r"(?:called|named|titled|=|:)?\s*"
    r"[`\"']?([A-Za-z0-9_\-. ]+?\.[A-Za-z0-9]{1,12})[`\"']?"
    r"|"
    r"(?:file|folder|directory)\s+(?:called|named)\s+"
    r"[`\"']?([A-Za-z0-9_\-. ]+?\.[A-Za-z0-9]{1,12})[`\"']?",
    re.IGNORECASE,
)

# Answer claims a name is *in* the listed folder (not merely mentioned).
_IN_FOLDER_CLAIM = re.compile(
    r"(?i)(?:"
    r"(?:^|\n)\s*(?:\d+[\.\)]\s*|[-*•]\s*)`([^`\n]{1,120})`"  # list item
    r"|"
    r"(?:in|inside|under|from)\s+(?:the\s+)?(?:folder|directory|listing|"
    r"downloads|desktop|documents|pictures)?[^.\n]{0,40}"
    r"[`\"']([A-Za-z0-9_\-. ]+?\.[A-Za-z0-9]{1,12})[`\"']"
    r"|"
    r"(?:contains?|includes?|has|found)\s+(?:the\s+)?(?:file\s+)?"
    r"[`\"']([A-Za-z0-9_\-. ]+?\.[A-Za-z0-9]{1,12})[`\"']"
    r"|"
    r"(?:file|folder)\s+[`\"']([A-Za-z0-9_\-. ]+?\.[A-Za-z0-9]{1,12})[`\"']"
    r"\s+(?:is|was)\s+(?:in|there|present)"
    r")"
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


def _transcript_events(transcript: Any) -> list[dict[str, Any]]:
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
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def _this_turn_events(transcript: Any) -> list[dict[str, Any]]:
    """Events after the latest user_turn / run_start boundary (same turn only)."""
    events = _transcript_events(transcript)
    if not events:
        return []
    boundary = -1
    for i, ev in enumerate(events):
        if ev.get("type") in ("user_turn", "run_start"):
            boundary = i
    if boundary < 0:
        return events
    return events[boundary + 1 :]


def list_directory_calls_this_turn(transcript: Any) -> list[dict[str, Any]]:
    """list_directory tool_call events from the current turn only."""
    out: list[dict[str, Any]] = []
    for ev in _this_turn_events(transcript):
        if ev.get("type") == "tool_call" and ev.get("name") == "list_directory":
            out.append(ev)
    return out


def last_list_directory_entries(transcript: Any) -> list[dict[str, Any]]:
    """Return entries from the latest *same-turn* list_directory tool_call."""
    best: list[dict[str, Any]] = []
    for ev in list_directory_calls_this_turn(transcript):
        entries = _entries_from_tool_result(ev.get("result"))
        if entries:
            best = entries
    return best


def last_list_directory_path(transcript: Any) -> str:
    """Path argument of the latest same-turn list_directory (or '')."""
    path = ""
    for ev in list_directory_calls_this_turn(transcript):
        args = ev.get("args") or {}
        if isinstance(args, dict) and args.get("path"):
            path = str(args.get("path") or "")
    return path


def last_size_sorted_listing(transcript: Any) -> list[dict[str, Any]]:
    """File entries from the latest same-turn list_directory, largest first."""
    best: list[dict[str, Any]] = []
    for ev in list_directory_calls_this_turn(transcript):
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


def names_user_asked_to_create(question: str) -> set[str]:
    """Basenames the user asked to create/write — never strip these."""
    names: set[str] = set()
    for m in _CREATE_NAME_RE.finditer(question or ""):
        raw = next((g for g in m.groups() if g), None)
        if not raw:
            continue
        base = raw.replace("\\", "/").split("/")[-1].strip().strip("`\"'")
        if base:
            names.add(base.lower())
    return names


def names_claimed_in_answer(answer: str) -> set[str]:
    """All file-like names mentioned in the answer (legacy / biggest-files)."""
    names: set[str] = set()
    for m in _NAME_IN_BACKTICKS.finditer(answer or ""):
        base = m.group(1).replace("\\", "/").split("/")[-1].strip()
        if base:
            names.add(base.lower())
    for m in _NAME_AS_PATH.finditer(answer or ""):
        names.add(m.group(1).lower())
    return names


_FOLDER_TALK = re.compile(
    r"(?i)\b("
    r"folder|directory|listing|downloads|desktop|documents|pictures|"
    r"contains?|includes?|files?\s+in|inside\s+that|in\s+that\s+folder|"
    r"in\s+the\s+folder|listed|listing"
    r")\b"
)


def _names_from_text_span(span: str) -> set[str]:
    names: set[str] = set()
    for m in _NAME_IN_BACKTICKS.finditer(span or ""):
        base = m.group(1).replace("\\", "/").split("/")[-1].strip()
        if base:
            names.add(base.lower())
    for m in _NAME_AS_PATH.finditer(span or ""):
        names.add(m.group(1).lower())
    return names


def names_claimed_in_listed_folder(
    answer: str,
    *,
    question: str = "",
    listed_path: str = "",
) -> set[str]:
    """Names the answer presents as being inside the listed folder.

    Excludes names the user asked to create. Numbered/bulleted listing lines
    and sentences that talk about the folder's contents count; bare mentions
    of a create-target do not.
    """
    create = names_user_asked_to_create(question)
    folder_leaf = ""
    if listed_path:
        folder_leaf = listed_path.replace("\\", "/").rstrip("/").split("/")[-1].lower()

    claimed: set[str] = set()

    # Numbered/bulleted lines (typical listing / biggest-files answer).
    for line in (answer or "").splitlines():
        if re.match(r"^\s*(?:\d+[\.\)]\s*|[-*•]\s*)", line):
            claimed |= _names_from_text_span(line)

    # Sentences that talk about folder contents.
    for sentence in re.split(r"(?<=[.!?])\s+", answer or ""):
        if _FOLDER_TALK.search(sentence):
            claimed |= _names_from_text_span(sentence)
        elif folder_leaf and re.search(rf"(?i)\b{re.escape(folder_leaf)}\b", sentence):
            claimed |= _names_from_text_span(sentence)

    for m in _IN_FOLDER_CLAIM.finditer(answer or ""):
        raw = next((g for g in m.groups() if g), None)
        if not raw:
            continue
        base = raw.replace("\\", "/").split("/")[-1].strip()
        if base:
            claimed.add(base.lower())

    return {n for n in claimed if n not in create}


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


def _strip_unknown_names(
    answer: str,
    known: set[str],
    *,
    only: Optional[set[str]] = None,
) -> tuple[str, list[str]]:
    """Remove backtick / extension-looking names not in known; return (text, removed).

    If ``only`` is set, only those basenames (lower) may be stripped.
    """
    removed: list[str] = []
    text = answer or ""
    only_l = {x.lower() for x in only} if only is not None else None

    def _bt(m: re.Match[str]) -> str:
        raw = m.group(1)
        base = raw.replace("\\", "/").split("/")[-1].strip()
        if not base:
            return m.group(0)
        low = base.lower()
        if low in known:
            return m.group(0)
        if only_l is not None and low not in only_l:
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
        low = name.lower()
        if low in known:
            return m.group(0)
        if only_l is not None and low not in only_l:
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
    """Same-turn rule: names presented as in the listed folder must appear there.

    Skips entirely when this turn did not call list_directory. Never strips
    names the user asked to create. Biggest-files questions still get a full
    rewrite from the size-sorted listing when needed.
    """
    entries = last_list_directory_entries(transcript)
    if not entries:
        return answer, None

    known = names_in_listing(entries)
    listed_path = last_list_directory_path(transcript)
    create_names = names_user_asked_to_create(question)

    # Special case: biggest/largest → prefer size-sorted rewrite when needed.
    if is_biggest_files_question(question):
        files = last_size_sorted_listing(transcript)
        if files:
            expected = {
                str(e.get("name") or "").lower()
                for e in files[:top_n]
                if e.get("name")
            }
            claimed = names_claimed_in_answer(answer) - create_names
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

    claimed = names_claimed_in_listed_folder(
        answer, question=question, listed_path=listed_path
    )
    if not claimed:
        return answer, None
    invented = sorted(c for c in claimed if c not in known)
    if not invented:
        return answer, None
    cleaned, removed = _strip_unknown_names(answer, known, only=set(invented))
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
