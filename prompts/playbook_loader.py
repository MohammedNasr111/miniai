"""Load the playbook for injection into the system prompt."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

PLAYBOOK_MAX_CHARS = 1500
DEFAULT_PLAYBOOK = Path(__file__).resolve().parent / "playbook.md"

_HEADER_PREFIXES = ("#",)


def playbook_path() -> Path:
    override = (os.environ.get("MINIAI_PLAYBOOK") or "").strip()
    if override:
        return Path(override)
    return DEFAULT_PLAYBOOK


def _strip_comment_only_lines(text: str) -> str:
    """Drop leading/trailing pure-comment lines; keep instructional body."""
    lines = text.splitlines()
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if body:
                body.append(line)
            continue
        if stripped.startswith("#") and not body:
            continue
        body.append(line)
    # Trim trailing blanks
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body).strip()


def load_playbook_text() -> str:
    """Return playbook body for the system prompt, or "" if missing/oversize/empty.

    Uses MINIAI_PLAYBOOK if set (trial temp path); otherwise prompts/playbook.md.
    Refuses (warning, empty) if body exceeds PLAYBOOK_MAX_CHARS.
    """
    path = playbook_path()
    if not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("playbook unreadable at %s: %s", path, exc)
        return ""
    body = _strip_comment_only_lines(raw)
    if not body:
        return ""
    if len(body) > PLAYBOOK_MAX_CHARS:
        logger.warning(
            "playbook at %s is %d chars (max %d); loading nothing",
            path,
            len(body),
            PLAYBOOK_MAX_CHARS,
        )
        return ""
    return body


def format_playbook_section(body: str) -> str:
    """Delimited system-prompt section; empty body → empty string."""
    if not body:
        return ""
    return (
        "Learned guidance (playbook):\n"
        f"{body}\n"
        "If any learned guidance conflicts with the rules below, the rules below win.\n"
    )
