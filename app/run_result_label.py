"""Plain-English run_tests / run_file / run_code result nodes for the trace."""

from __future__ import annotations

import re
from typing import Optional

from tools.code.pytest_summary import parse_pytest_summary


def run_result_node(
    tool: str, result_text: str, *, outcome: str = "ok"
) -> tuple[str, str]:
    """Return (label, class_key) for a coding-run tool result.

    class_key: ``verify`` (verdigris) on clean pass, ``danger`` (brick) on fail.
    """
    name = (tool or "").strip()
    body = result_text or ""
    outcome_l = (outcome or "").lower()
    if outcome_l in ("denied", "deny", "cancelled", "canceled"):
        return (f"Didn't run ({name.replace('_', ' ')})", "denied")

    if name == "run_tests":
        # Prefer an explicit collection / import failure line when present.
        mod = re.search(
            r"(ModuleNotFoundError:\s*[^\n]+)", body
        ) or re.search(r"(ImportError:\s*[^\n]+)", body)
        if re.search(r"(?i)error collecting|errors during collection", body) and mod:
            label = f"Ran tests: 1 error (collection): {mod.group(1).strip()}"
            return (label[:220], "danger")
        summary = parse_pytest_summary(body)
        # Normalize "Tests: …" → "Ran tests: …"
        label = summary
        if label.lower().startswith("tests:"):
            label = "Ran tests:" + label[6:]
        elif not label.lower().startswith("ran tests"):
            label = "Ran tests: " + label
        # Collection / ModuleNotFound → brick
        low = body.lower() + " " + label.lower()
        bad = bool(
            re.search(
                r"(?i)\b(failing|failed|error|modulenotfound|collection)\b",
                low,
            )
        ) or ("exit_code: 0" not in body and "exit_code:" in body)
        # Prefer exit_code when present
        m = re.search(r"exit_code:\s*(-?\d+)", body)
        if m:
            try:
                bad = int(m.group(1)) != 0
            except ValueError:
                pass
        return (label[:220], "danger" if bad else "verify")

    if name == "run_file":
        m = re.search(r"exit_code:\s*(-?\d+)", body)
        code = None
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
        if code == 0:
            return ("Ran file: exit 0", "verify")
        if code is not None:
            return (f"Ran file: exit {code}", "danger")
        return ("Ran a file", "change")

    if name == "run_code":
        m = re.search(r"exit_code:\s*(-?\d+)", body)
        code = None
        if m:
            try:
                code = int(m.group(1))
            except ValueError:
                code = None
        if code == 0:
            return ("Ran code: exit 0", "verify")
        if code is not None:
            return (f"Ran code: exit {code}", "danger")
        return ("Ran code", "change")

    return ("", "")
