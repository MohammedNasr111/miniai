"""Page-date labels and recency notes for web_research (labels only)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlparse

# Question must look like a recency ask (case-insensitive).
_RECENCY_QUESTION_RE = re.compile(
    r"\b("
    r"latest|newest|current|currently|most\s+recent|up\s+to\s+date|as\s+of"
    r")\b",
    re.I,
)

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def today_date() -> date:
    """Same calendar day the agent system prompt uses."""
    return datetime.now().astimezone().date()


def is_recency_question(question: str) -> bool:
    return bool(_RECENCY_QUESTION_RE.search(question or ""))


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "unknown"
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def parse_iso_or_text_date(raw: str, *, today: Optional[date] = None) -> Optional[date]:
    """Parse one date string; reject dates after today."""
    if not raw or not str(raw).strip():
        return None
    today = today or today_date()
    text = str(raw).strip()
    # ISO date or datetime prefix
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
    # October 9, 2026 / Oct 9, 2026
    m = re.search(
        r"\b("
        + "|".join(_MONTHS.keys())
        + r")\s+(\d{1,2}),?\s+(\d{4})\b",
        text,
        re.I,
    )
    if m:
        month = _MONTHS[m.group(1).lower()]
        return _make_date(int(m.group(3)), month, int(m.group(2)), today)
    # 9 October 2026
    m = re.search(
        r"\b(\d{1,2})\s+("
        + "|".join(_MONTHS.keys())
        + r")\s+(\d{4})\b",
        text,
        re.I,
    )
    if m:
        month = _MONTHS[m.group(2).lower()]
        return _make_date(int(m.group(3)), month, int(m.group(1)), today)
    return None


def _make_date(year: int, month: int, day: int, today: date) -> Optional[date]:
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if d > today:
        return None
    return d


def find_newest_date_in_text(text: str, *, today: Optional[date] = None) -> Optional[date]:
    """Newest plausible date in page text; ignore dates after today."""
    today = today or today_date()
    if not text:
        return None
    found: list[date] = []
    # ISO
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        d = _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d:
            found.append(d)
    # Month name forms
    month_alt = "|".join(_MONTHS.keys())
    for m in re.finditer(
        rf"\b({month_alt})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", text, re.I
    ):
        d = _make_date(
            int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)), today
        )
        if d:
            found.append(d)
    for m in re.finditer(
        rf"\b(\d{{1,2}})\s+({month_alt})\s+(\d{{4}})\b", text, re.I
    ):
        d = _make_date(
            int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)), today
        )
        if d:
            found.append(d)
    if not found:
        return None
    return max(found)


def resolve_page_date(
    *,
    published_date: Optional[str] = None,
    page_text: str = "",
    today: Optional[date] = None,
) -> Optional[date]:
    today = today or today_date()
    if published_date:
        d = parse_iso_or_text_date(published_date, today=today)
        if d is not None:
            return d
    return find_newest_date_in_text(page_text, today=today)


def format_age(page_day: date, *, today: Optional[date] = None) -> str:
    today = today or today_date()
    days = (today - page_day).days
    if days < 0:
        days = 0
    if days < 60:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} before today"
    # Whole months, at least 1 if >= 60 days.
    months = max(1, round(days / 30.44))
    unit = "month" if months == 1 else "months"
    return f"about {months} {unit} before today"


def format_page_date_label(
    page_day: Optional[date], *, today: Optional[date] = None
) -> str:
    if page_day is None:
        return "unknown"
    today = today or today_date()
    return f"{page_day.isoformat()} ({format_age(page_day, today=today)})"


def source_date_header_line(
    source_rank: int,
    url: str,
    page_day: Optional[date],
    *,
    today: Optional[date] = None,
) -> str:
    domain = domain_of(url)
    label = format_page_date_label(page_day, today=today)
    return f"[source {source_rank}] {domain} — page date: {label}"


def build_recency_note(
    sources: list[tuple[str, Optional[date]]],
    *,
    today: Optional[date] = None,
) -> str:
    """Note placed AFTER the untrusted end marker. Domains + dates only."""
    today = today or today_date()
    lines = [
        (
            "Recency note (computed by MiniAI, not from the pages): today is "
            f"{today.isoformat()}. Sources dated more than 6 months ago may be "
            "out of date for this question. If a newer or official source lists "
            "a newer version or date, prefer it and say so."
        )
    ]
    for url, page_day in sources:
        domain = domain_of(url)
        label = format_page_date_label(page_day, today=today)
        lines.append(f"{domain} — page date: {label}")
    return "\n".join(lines)
