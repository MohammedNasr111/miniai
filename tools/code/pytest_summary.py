"""Parse pytest -q --tb=short output into a short failure summary (≤1500 chars)."""

from __future__ import annotations

import re
from typing import Optional

MAX_SUMMARY_CHARS = 1500

_SUMMARY_LINE = re.compile(
    r"=+\s*([\d\s\w,]+)\s+in\s+[\d.]+s\s*=+",
    re.IGNORECASE,
)
_FAILED = re.compile(
    r"^FAILED\s+(\S+?)(?:\s+-\s+(.*))?$",
    re.MULTILINE,
)
_ERROR = re.compile(
    r"^ERROR\s+(\S+?)(?:\s+-\s+(.*))?$",
    re.MULTILINE,
)
_FILE_LINE = re.compile(r"^([^\s:]+\.py):(\d+):\s*(.*)$", re.MULTILINE)
_ASSERT = re.compile(r"^E\s+(.*)$", re.MULTILINE)
_TEST_HEADER = re.compile(r"^_{3,}\s*([\w\[\]().:-]+)\s*_{3,}\s*$", re.MULTILINE)
_PASSED_COUNT = re.compile(r"(\d+)\s+passed", re.IGNORECASE)
_FAILED_COUNT = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
_ERROR_COUNT = re.compile(r"(\d+)\s+error", re.IGNORECASE)
_COLLECT = re.compile(
    r"(?i)(error collecting|errors during collection|Interrupted:.*?collection)",
)


def unwrap_run_output(text: str) -> str:
    """Strip untrusted markers / format_run_result framing to pytest body."""
    raw = text or ""
    begin = "<<<BEGIN UNTRUSTED CODE OUTPUT>>>"
    end = "<<<END UNTRUSTED CODE OUTPUT>>>"
    if begin in raw and end in raw:
        raw = raw.split(begin, 1)[1].split(end, 1)[0]
    # Prefer stdout section from format_run_result
    if "--- stdout ---" in raw:
        body = raw.split("--- stdout ---", 1)[1]
        if "--- stderr ---" in body:
            out, err = body.split("--- stderr ---", 1)
            raw = (out.strip() + "\n" + err.strip()).strip()
        else:
            raw = body.strip()
    return raw


def parse_pytest_summary(text: str, *, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    """Return a compact status string for the model (never the full pytest dump)."""
    body = unwrap_run_output(text)
    if not body.strip():
        return "Tests: no output from pytest."

    passed = _int_search(_PASSED_COUNT, body)
    failed = _int_search(_FAILED_COUNT, body)
    errors = _int_search(_ERROR_COUNT, body)

    failures: list[str] = []
    for m in _FAILED.finditer(body):
        tid = m.group(1).strip()
        msg = (m.group(2) or "").strip()
        failures.append(_format_one(tid, msg, body))
    for m in _ERROR.finditer(body):
        tid = m.group(1).strip()
        msg = (m.group(2) or "").strip()
        failures.append(_format_one(tid, msg, body, kind="error"))

    if not failures and _COLLECT.search(body):
        # Collection error without FAILED lines
        loc = _FILE_LINE.search(body)
        assert_m = _ASSERT.search(body)
        bit = ""
        if loc:
            bit = _short_loc(f"{loc.group(1)}:{loc.group(2)}")
        amsg = assert_m.group(1).strip() if assert_m else "collection error"
        # Prefer SyntaxError / ImportError hints from the body
        syn = re.search(
            r"(?i)(SyntaxError|ImportError|ModuleNotFoundError)[^\n]*", body
        )
        if syn:
            amsg = re.sub(r"\s+", " ", syn.group(0).strip())[:160]
        failures.append(f"collection — {bit} {amsg}".strip())

    if failed is None and errors is None and not failures:
        # All green or unknown
        if passed is not None and "failed" not in body.lower() and "error" not in body.lower():
            return f"Tests: {passed} passed."
        if re.search(r"(?i)\bpassed\b", body) and not re.search(
            r"(?i)\b(failed|error)\b", body
        ):
            n = passed if passed is not None else "?"
            return f"Tests: {n} passed."
        # Fallback: first non-empty lines
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()][:4]
        return _clip("Tests: " + " | ".join(lines), max_chars)

    parts: list[str] = []
    counts = []
    if passed is not None:
        counts.append(f"{passed} passed")
    if failed:
        counts.append(f"{failed} failing")
    if errors:
        counts.append(f"{errors} error(s)")
    head = "Tests: " + (", ".join(counts) if counts else "finished with failures")
    if failures:
        # Keep first 3 failure details
        detail = "; ".join(failures[:3])
        head = f"{head}: {detail}"
    return _clip(head, max_chars)


_ASSERT_SRC = re.compile(r"^\s*(assert\b.+)$", re.MULTILINE)


def _short_loc(path_line: str) -> str:
    """Prefer a workspace-relative or basename:line over huge absolute paths."""
    if not path_line:
        return ""
    # Keep trailing file.py:lineno
    m = re.search(r"([^\\/]+\.py):(\d+)\s*$", path_line.replace("\\", "/"))
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    parts = path_line.replace("\\", "/").split("/")
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path_line


def _failure_window(body: str, test_id: str, name: str) -> str:
    """Slice the FAILURES block for this test (not the trailing summary line)."""
    # Prefer the underlined header pytest prints in the FAILURES section.
    hdr = re.search(
        rf"^_+\s*{re.escape(name)}\s*_+\s*$", body, re.MULTILINE
    )
    if hdr:
        return body[hdr.start() : hdr.start() + 900]
    # Fall back to first file.py:line mention of the test name
    for m in re.finditer(
        rf"^.*?\.py:\d+:\s+in\s+{re.escape(name)}\s*$", body, re.MULTILINE
    ):
        return body[m.start() : m.start() + 900]
    idx = body.find(name)
    if idx >= 0:
        return body[idx : idx + 900]
    idx = body.find(test_id)
    if idx >= 0:
        return body[max(0, idx - 400) : idx + 200]
    return body[:900]


def _format_one(
    test_id: str,
    short_msg: str,
    body: str,
    *,
    kind: str = "fail",
) -> str:
    # Prefer short summary message; enrich with file:line + assert source
    name = test_id.split("::")[-1] if "::" in test_id else test_id
    loc = ""
    window = _failure_window(body, test_id, name)
    fl = _FILE_LINE.search(window)
    if fl:
        loc = _short_loc(f"{fl.group(1)}:{fl.group(2)}")
    amsg = short_msg
    if not amsg:
        am = _ASSERT.search(window)
        if am:
            amsg = am.group(1).strip()
    src = _ASSERT_SRC.search(window)
    if src:
        # Keep internal whitespace — it is often the bug (e.g. "a   b").
        src_line = src.group(1).strip()[:160]
        if src_line:
            amsg = src_line
    if amsg and not amsg.lstrip().startswith("assert"):
        amsg = re.sub(r"\s+", " ", amsg).strip()
    amsg = (amsg or "")[:220]
    bits = [name]
    if loc:
        bits.append(loc)
    if amsg:
        bits.append(amsg)
    prefix = "error" if kind == "error" else "fail"
    return f"{prefix} {bits[0]}" + (
        " — " + " — ".join(bits[1:]) if len(bits) > 1 else ""
    )


def _int_search(rx: re.Pattern[str], text: str) -> Optional[int]:
    m = rx.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _clip(s: str, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"
