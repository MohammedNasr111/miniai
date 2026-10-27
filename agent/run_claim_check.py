"""Deterministic honesty check for fabricated test-run claims."""

from __future__ import annotations

import re
from typing import Any, Optional

RUN_TOOLS = frozenset({"run_tests", "run_file", "run_code"})

_CLAIM_RE = re.compile(
    r"(?i)"
    r"(?:\btests?\s+pass(?:ed|es)?\b|"
    r"\ball\s+tests\b|"
    r"\bsuccessfully\s+ran\b|"
    r"\bpassed\b|"
    r"\bworks\b|"
    r"\bexit[_\s-]?code\s*[:=]?\s*0\b|"
    r"\d+\s+passed\b|"
    r"platform\s+win\d+|"
    r"pytest-\d|"
    r"rootdir\s*:|"
    r"={3,}\s*\d+\s+passed)"
)

_OUTPUT_HINT_RE = re.compile(
    r"(?i)(?:platform\s+win|pytest-|rootdir\s*:|={5,}|---\s*stdout\s*---|"
    r"collected\s+\d+\s+item|FAILED\s+\S+|PASSED\s+\S+|"
    r"\d+\s+passed(?:\s+in\s+[\d.]+s)?)"
)

_EXIT_RE = re.compile(r"exit_code:\s*([-\d]+|None)", re.I)

CORRECTION_TMPL = (
    "\n\n⚠ Correction: the last real test run in this conversation was "
    "{status}, exit code {code}. Earlier wording that said otherwise "
    "was not supported by an actual run."
)

# Cleared at the start of each user-turn tool loop.
_turn_runs: list[dict[str, Any]] = []


def reset_turn_runs() -> None:
    _turn_runs.clear()


def get_turn_runs() -> list[dict[str, Any]]:
    return list(_turn_runs)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_code_markers(text: str) -> str:
    begin = "<<<BEGIN UNTRUSTED CODE OUTPUT>>>"
    end = "<<<END UNTRUSTED CODE OUTPUT>>>"
    if begin in text and end in text:
        start = text.find(begin) + len(begin)
        stop = text.find(end, start)
        if stop != -1:
            return text[start:stop].strip()
    return text


def record_run_tool(name: str, result_text: str) -> Optional[dict[str, Any]]:
    """Parse a run_* tool result and store a turn record. Returns the record."""
    if name not in RUN_TOOLS:
        return None
    body = _strip_code_markers(result_text or "")
    m = _EXIT_RE.search(body) or _EXIT_RE.search(result_text or "")
    if m and m.group(1) != "None":
        try:
            exit_code: Optional[int] = int(m.group(1))
        except ValueError:
            exit_code = None
    else:
        exit_code = None
        # Denied / refused / errors before a run
        low = (result_text or "").lower()
        if "denied" in low or "refused" in low or result_text.startswith("Error:"):
            exit_code = None
    ok = exit_code == 0
    lines = body.splitlines()
    preview_lines = lines[:40]
    preview = "\n".join(preview_lines)
    status = "PASS" if ok else "FAIL"
    summary = f"{name}: {status} (exit_code={exit_code})"
    record = {
        "tool": name,
        "exit_code": exit_code,
        "ok": ok,
        "summary": summary,
        "output_preview": preview,
        "normalized_full": normalize_ws(body),
    }
    _turn_runs.append(record)
    return record


def evidence_summary_line(record: dict[str, Any]) -> str:
    """Short evidence-store line for the turn (exit + preview head)."""
    head = (record.get("output_preview") or "").splitlines()[:5]
    return (
        f"[run_record] {record.get('summary')}\n"
        + "\n".join(head)
    )


def answer_claims_run_success(answer: str) -> bool:
    return bool(_CLAIM_RE.search(answer or ""))


_TESTS_PASSED_PREFIX = re.compile(
    r"(?i)^\s*tests?\s+passed\.?\s*",
)
_FAILURE_IN_ANSWER = re.compile(
    r"(?i)\b(?:\d+\s+failing|\d+\s+failed|\bfailing\b|\bfailed\b|"
    r"assertion\s*err|error(?:s)?\b)",
)


def strip_contradictory_pass_claim(answer: str) -> str:
    """Drop a leading 'Tests passed' when the same answer reports failures."""
    text = answer or ""
    if not _TESTS_PASSED_PREFIX.search(text):
        return text
    # Prefer the honest "Tests: …" clause when present.
    idx = text.find("Tests:")
    if idx >= 0 and _FAILURE_IN_ANSWER.search(text[idx:]):
        return text[idx:].lstrip()
    if _FAILURE_IN_ANSWER.search(text):
        return _TESTS_PASSED_PREFIX.sub("", text, count=1).lstrip()
    return text


def _is_compact_tests_summary(text: str) -> bool:
    """True for our auto-test one-liners (not a fabricated pytest dump)."""
    p = (text or "").strip()
    if not p.startswith("Tests:"):
        return False
    # Compact summaries stay one short paragraph; dumps have session headers.
    if "\n" in p and ("platform " in p.lower() or "rootdir" in p.lower()):
        return False
    return len(p) < 800


def _candidate_blocks(answer: str) -> list[str]:
    """Extract fenced code blocks and dense output-like paragraphs."""
    blocks: list[str] = []
    for m in re.finditer(r"```(?:[a-zA-Z0-9_+-]*)\n(.*?)```", answer or "", re.S):
        body = m.group(1).strip()
        if not _is_compact_tests_summary(body):
            blocks.append(body)
    # Also long indented / multi-line chunks that look like pytest
    for para in re.split(r"\n{2,}", answer or ""):
        p = para.strip()
        if _is_compact_tests_summary(p):
            continue
        if len(p) >= 60 and _OUTPUT_HINT_RE.search(p):
            if p not in blocks:
                blocks.append(p)
    return blocks


def block_in_records(block: str, runs: list[dict[str, Any]]) -> bool:
    needle = normalize_ws(block)
    if len(needle) < 40:
        return True
    for r in runs:
        hay = r.get("normalized_full") or ""
        if not hay:
            continue
        if needle in hay or hay in needle:
            return True
        # Substantial overlap: first 80 chars of needle in hay
        if len(needle) >= 80 and needle[:80] in hay:
            return True
    return False


def check_run_claims(
    answer: str,
    runs: Optional[list[dict[str, Any]]] = None,
    transcript: Any = None,
) -> str:
    """Replace fabricated run transcripts and append a correction when needed."""
    if runs is None:
        runs = list(_turn_runs)
    original = answer or ""
    # Always strip an internal "Tests passed" + failing contradiction first.
    answer = strip_contradictory_pass_claim(original)
    # If we only needed to drop a false "Tests passed" prefix, stop here —
    # the remaining "Tests: … failing" line is already the honest status.
    if (
        answer != original
        and _is_compact_tests_summary(answer)
        and _FAILURE_IN_ANSWER.search(answer)
    ):
        if transcript is not None:
            try:
                transcript.write(
                    "run_claim_check",
                    fired=True,
                    stripped_pass_claim=True,
                    claims=True,
                )
            except Exception:
                pass
        return answer.strip()
    claims = answer_claims_run_success(answer)
    blocks = _candidate_blocks(answer) if claims or _OUTPUT_HINT_RE.search(answer or "") else []
    fabricated = [
        b for b in blocks if _OUTPUT_HINT_RE.search(b) and not block_in_records(b, runs)
    ]
    last = runs[-1] if runs else None
    # Latest real run in the turn decides — an earlier green run must not
    # excuse a success claim after a later failure.
    last_ok = bool(last.get("ok")) if last is not None else False
    any_ok = any(bool(r.get("ok")) for r in runs)
    # Fabricated output always triggers; success claims need the *latest* exit 0
    need = bool(fabricated) or (claims and not last_ok)
    detail = {
        "fired": need,
        "claims": claims,
        "any_ok": any_ok,
        "last_ok": last_ok,
        "runs": [
            {"tool": r.get("tool"), "exit_code": r.get("exit_code"), "ok": r.get("ok")}
            for r in runs
        ],
        "fabricated_blocks": len(fabricated),
    }
    if transcript is not None:
        try:
            transcript.write("run_claim_check", **detail)
        except Exception:
            pass
    if not need:
        return answer

    new_answer = answer
    real_preview = (
        last.get("output_preview")
        if last and last.get("output_preview")
        else "(no run_* tool result was recorded in this turn)"
    )
    for block in fabricated:
        # Prefer exact replace; fall back to first occurrence of normalized match
        if block in new_answer:
            new_answer = new_answer.replace(block, real_preview, 1)
        else:
            # fenced form
            fenced = f"```\n{block}\n```"
            if fenced in new_answer:
                new_answer = new_answer.replace(fenced, f"```\n{real_preview}\n```", 1)

    new_answer = strip_contradictory_pass_claim(new_answer)

    if last is not None and last.get("exit_code") is not None:
        status = "PASS" if last.get("ok") else "FAIL"
        code: Any = last.get("exit_code")
    elif last is not None:
        status = "FAIL"
        code = "n/a"
    else:
        status = "FAIL"
        code = "n/a"
    # When the answer already carries an honest "Tests: N passed, M failing"
    # summary, prefer that alone (no "Tests passed", no extra correction note).
    if (
        "Tests:" in new_answer
        and _FAILURE_IN_ANSWER.search(new_answer)
        and not fabricated
    ):
        idx = new_answer.find("Tests:")
        return new_answer[idx:].strip()
    note = CORRECTION_TMPL.format(status=status, code=code)
    if "⚠ Correction: the last real test run" not in new_answer:
        new_answer = new_answer.rstrip() + note
    return new_answer
