"""Code-side anti-overfit / safety filter for playbook candidates."""

from __future__ import annotations

import re
from typing import Any

# Product names that appear in freshness / holdout / common web prompts.
PRODUCT_NAMES = (
    "Python",
    "Node",
    "Node.js",
    "Linux",
    "Firefox",
    "Go",
    "Golang",
    "Rust",
    "PostgreSQL",
    "Postgres",
    "Mitochondria",
    "ATP",
)

FORBIDDEN_WORDS = (
    "approve",
    "confirm",
    "permission",
    "untrusted",
    "ignore",
    "skip",
    "bypass",
    "override",
    "password",
    "secret",
)

_VERSION_RE = re.compile(r"\d+\.\d+")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\.]*")


def _tool_names() -> set[str]:
    try:
        from tools.registry import TOOL_FUNCTIONS

        return set(TOOL_FUNCTIONS.keys())
    except Exception:
        return set()


def extract_failure_context(failures: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect strings used by the filter from failed eval rows."""
    prompts: list[str] = []
    reasons: list[str] = []
    answers: list[str] = []
    versions: set[str] = set()
    products: set[str] = set()
    for row in failures:
        prompt = str(row.get("prompt") or "")
        reason = str(row.get("reason") or "")
        answer = str(row.get("answer") or "")
        if prompt:
            prompts.append(prompt)
        if reason:
            reasons.append(reason)
        if answer:
            answers.append(answer)
        for blob in (prompt, reason, answer, str(row.get("evidence") or "")):
            for m in _VERSION_RE.findall(blob):
                versions.add(m)
        low = prompt.lower()
        for name in PRODUCT_NAMES:
            if name.lower() in low:
                products.add(name)
    return {
        "prompts": prompts,
        "reasons": reasons,
        "answers": answers,
        "versions": sorted(versions),
        "products": sorted(products),
    }


def filter_candidate(
    instruction: str,
    *,
    failures: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). ok False → reject with reason."""
    text = (instruction or "").strip()
    if not text:
        return False, "empty instruction"
    if len(text) > 300:
        return False, f"instruction longer than 300 chars ({len(text)})"

    ctx = context or extract_failure_context(failures or [])
    low = text.lower()

    # Version numbers / truth tokens seen in the failures (any \d+\.\d+).
    for ver in ctx.get("versions") or []:
        if ver and re.search(rf"(?<![\d.]){re.escape(ver)}(?![\d])", text):
            return False, f"contains failure version token {ver!r}"

    for prompt in ctx.get("prompts") or []:
        p = prompt.strip()
        if len(p) >= 12 and p.lower() in low:
            return False, "contains task prompt text"

    for name in ctx.get("products") or []:
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            return False, f"contains product name {name!r}"
    # Also block the full PRODUCT_NAMES list when present in any failure prompt.
    for name in PRODUCT_NAMES:
        if any(name.lower() in (p or "").lower() for p in (ctx.get("prompts") or [])):
            if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                return False, f"contains product name {name!r}"

    tools = _tool_names()
    for tok in _WORD_RE.findall(text):
        if tok in tools or tok.lower() in {t.lower() for t in tools}:
            return False, f"contains tool name {tok!r}"

    for word in FORBIDDEN_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            return False, f"contains forbidden word {word!r}"

    return True, "ok"
