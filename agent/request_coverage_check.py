"""Round 13 Part 4(c) — request-coverage check after write_file / create_file.

After a turn writes a file, compare explicit (and lightly implied) request
items with the file content. At most one corrective re-run per turn.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

_fired_this_turn = False


def reset_request_coverage_state() -> None:
    global _fired_this_turn
    _fired_this_turn = False


def coverage_already_fired() -> bool:
    return _fired_this_turn


def mark_coverage_fired() -> None:
    global _fired_this_turn
    _fired_this_turn = True


def extract_file_coverage_items(user_text: str) -> list[dict[str, Any]]:
    """Noun-phrase style deliverables the written file should cover."""
    low = (user_text or "").lower()
    items: list[dict[str, Any]] = []
    if re.search(r"\bbest\b", low):
        items.append(
            {
                "id": "best",
                "label": "best month/item",
                "patterns": [re.compile(r"\bbest\b", re.I)],
            }
        )
    if re.search(r"\bworst\b", low):
        items.append(
            {
                "id": "worst",
                "label": "worst month/item",
                "patterns": [re.compile(r"\bworst\b", re.I)],
            }
        )
    if re.search(r"\btotal\b|\bsum\b|\baltogether\b", low):
        items.append(
            {
                "id": "total",
                "label": "total",
                "patterns": [
                    re.compile(r"\btotal\b", re.I),
                    re.compile(r"\bsum\b", re.I),
                    re.compile(r"\baltogether\b", re.I),
                ],
            }
        )
    # Combine CSVs / revenue into a summary implies an overall total line.
    if (
        re.search(r"\bcombine\b", low)
        and re.search(r"\b(csv|csvs|revenue|summary)\b", low)
        and not any(i["id"] == "total" for i in items)
    ):
        items.append(
            {
                "id": "total",
                "label": "overall total",
                "implied": True,
                "patterns": [
                    re.compile(r"\btotal\b", re.I),
                    re.compile(r"\bsum\b", re.I),
                    re.compile(r"overall", re.I),
                    re.compile(r"all\s+months", re.I),
                ],
            }
        )
    return items


def missing_coverage_in_text(
    user_text: str, file_text: str
) -> list[dict[str, Any]]:
    items = extract_file_coverage_items(user_text)
    missing = []
    body = file_text or ""
    for item in items:
        if any(p.search(body) for p in item["patterns"]):
            continue
        missing.append(item)
    return missing


def find_written_paths_needing_coverage(
    user_text: str,
    *,
    succeeded_tools: Optional[set[str]] = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return (paths, missing_items) for the first written file missing coverage."""
    from agent.action_claim_check import get_fs_verify_targets

    items = extract_file_coverage_items(user_text)
    if not items:
        return [], []
    succeeded = succeeded_tools
    if succeeded is None:
        from agent.action_claim_check import get_succeeded_tools

        succeeded = get_succeeded_tools()
    if not ({"write_file", "create_file"} & set(succeeded or set())):
        return [], []
    targets = get_fs_verify_targets()
    for t in targets:
        # Targets are (tool_name, path, was_dir) tuples.
        if isinstance(t, (tuple, list)) and len(t) >= 3:
            tool_name, path, was_dir = str(t[0]), str(t[1]), bool(t[2])
        elif isinstance(t, dict):
            tool_name = str(t.get("tool") or t.get("name") or "")
            path = str(t.get("path") or "")
            was_dir = bool(t.get("was_dir"))
        else:
            continue
        if tool_name not in ("write_file", "create_file"):
            continue
        if not path or was_dir:
            continue
        try:
            body = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        missing = missing_coverage_in_text(user_text, body)
        if missing:
            return [path], missing
    return [], []


def coverage_rerun_note(path: str, missing: list[dict[str, Any]]) -> str:
    labels = ", ".join(m["label"] for m in missing)
    return (
        f"Before finishing: the file you wrote at {path} is missing "
        f"requested item(s): {labels}. Update that same file with "
        f"write_file or create_file so every listed item from the user "
        f"request is present, then stop."
    )


def maybe_run_request_coverage(
    *,
    provider: Any,
    history: list[Any],
    question: str,
    call_model_fn: Any,
    consume_tool_round_fn: Any,
    transcript: Any = None,
    on_stream_clear: Any = None,
    clear_fn: Any = None,
    max_tool_rounds: int = 4,
) -> dict[str, Any]:
    """One corrective model+tools pass if a written file misses coverage."""
    detail: dict[str, Any] = {
        "fired": False,
        "reran": False,
        "paths": [],
        "missing": [],
    }
    try:
        from config import settings as _settings

        if not getattr(_settings, "FEATURE_REQUEST_COVERAGE", True):
            detail["skipped"] = "feature_off"
            return detail
    except Exception:
        pass
    if coverage_already_fired():
        detail["skipped"] = "already_fired"
        return detail
    paths, missing = find_written_paths_needing_coverage(question)
    detail["paths"] = paths
    detail["missing"] = [{"id": m["id"], "label": m["label"]} for m in missing]
    if not paths or not missing:
        return detail
    mark_coverage_fired()
    detail["fired"] = True
    note = coverage_rerun_note(paths[0], missing)
    from llm.base import ChatMessage

    history.append(ChatMessage(role="system", content=note))
    if transcript is not None:
        try:
            transcript.write("request_coverage_check", event="rerun", **detail)
        except Exception:
            pass
    if on_stream_clear is not None and clear_fn is not None:
        try:
            clear_fn()
        except Exception:
            pass
    response = call_model_fn(provider, history, transcript)
    extra = 0
    while getattr(response, "tool_calls", None) and extra < max_tool_rounds:
        response = consume_tool_round_fn(response, next_call=call_model_fn)
        extra += 1
    detail["reran"] = True
    detail["extra_tool_rounds"] = extra
    detail["response"] = response
    if transcript is not None:
        try:
            # Don't serialize the response object into the transcript.
            safe = {k: v for k, v in detail.items() if k != "response"}
            transcript.write("request_coverage_check", event="done", **safe)
        except Exception:
            pass
    return detail
