"""Round 11 — plan-first for long multi-step tasks (local + opt-in Groq)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from llm.base import ChatMessage, ChatResponse

logger = logging.getLogger(__name__)

ACTION_VERBS = frozenset(
    {
        "create",
        "write",
        "build",
        "move",
        "organise",
        "organize",
        "run",
        "test",
        "fix",
        "read",
        "summarise",
        "summarize",
        "compare",
        "save",
        "combine",
        "install",
        "delete",
        "copy",
        "edit",
        "make",
        "add",
        "include",
    }
)

PLANNING_INSTRUCTION = (
    "Write a short plan JSON only for the user's request; don't call tools. "
    'Schema: {"steps":[{"step":"...","tool_hint":"<tool name or none>",'
    '"done_when":"<a condition a tool result can prove>"}]} with at most 8 steps.'
)

PLAN_SYSTEM_PREFIX = (
    "Plan for this task:\n{plan_text}\n"
    "Work through every step; check each done_when with a tool result before finishing."
)

FINISH_GUARD_INSTRUCTION = (
    "For each step in the plan above, say whether its done_when is shown by a "
    "tool result in this turn. If any isn't, continue working with tools; "
    "otherwise give the final answer."
)

_MAX_STEPS = 8

# Turn-local plan state (UI + finish guard).
_current_plan: Optional[dict[str, Any]] = None
_finish_guard_fired: bool = False
_plan_note: str = ""  # visible fallback note (e.g. Groq → local)
_on_plan: Optional[Callable[[dict[str, Any]], None]] = None


def set_plan_hook(cb: Optional[Callable[[dict[str, Any]], None]]) -> None:
    global _on_plan
    _on_plan = cb


def reset_plan_turn() -> None:
    global _current_plan, _finish_guard_fired, _plan_note
    _current_plan = None
    _finish_guard_fired = False
    _plan_note = ""


def current_plan() -> Optional[dict[str, Any]]:
    return dict(_current_plan) if _current_plan else None


def plan_note() -> str:
    return _plan_note


def finish_guard_fired() -> bool:
    return _finish_guard_fired


def mark_finish_guard_fired() -> None:
    global _finish_guard_fired
    _finish_guard_fired = True


def effective_planner_mode() -> str:
    """Resolve planner mode: env MINIAI_PLANNER, else prefs, else settings."""
    import os

    env = os.environ.get("MINIAI_PLANNER", "").strip().lower()
    if env in ("off", "local", "groq"):
        return env
    try:
        from app.prefs import get_planner_mode

        return get_planner_mode()
    except Exception:
        pass
    try:
        from config import settings

        m = str(getattr(settings, "PLANNER_MODE", "off") or "off").lower()
        return m if m in ("off", "local", "groq") else "off"
    except Exception:
        return "off"


def _tokenize_verbs(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z']+", text or "")
    found: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in ACTION_VERBS:
            found.append(lw)
        # Gerunds / past: organising, organised, building, built
        for stem in ACTION_VERBS:
            if lw.startswith(stem) and len(lw) <= len(stem) + 4:
                found.append(stem)
                break
    return found


def needs_plan(question: str) -> bool:
    """True for multi-step requests; never for chat or single lookups."""
    q = (question or "").strip()
    if not q:
        return False
    low = q.lower()
    # Pure greetings / short chat
    if len(q) < 40 and re.match(
        r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no)\b", low
    ):
        return False
    verbs = _tokenize_verbs(q)
    uniq = []
    for v in verbs:
        if v not in uniq:
            uniq.append(v)
    if len(uniq) >= 2:
        return True
    if re.search(r"\band\s+then\b", low):
        return True
    if re.search(r"\b(project|app)\b", low):
        return True
    if len(q) >= 140 and len(uniq) >= 1:
        return True
    return False


def parse_plan_json(text: str) -> Optional[dict[str, Any]]:
    """Parse/repair plan JSON from model content. Returns {steps: [...]} or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    # Strip markdown fences / thinking wrappers.
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    # Prefer outermost {...}
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    chunk = raw[start : end + 1]
    data = None
    try:
        data = json.loads(chunk)
    except json.JSONDecodeError:
        # Trailing commas / single quotes repair
        repaired = re.sub(r",\s*}", "}", chunk)
        repaired = re.sub(r",\s*]", "]", repaired)
        repaired = repaired.replace("'", '"')
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    steps_raw = data.get("steps")
    if steps_raw is None and "step" in data:
        steps_raw = [data]
    if not isinstance(steps_raw, list) or not steps_raw:
        return None
    steps: list[dict[str, str]] = []
    for item in steps_raw[:_MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        step = str(item.get("step") or item.get("text") or "").strip()
        if not step:
            continue
        hint = str(item.get("tool_hint") or item.get("tool") or "none").strip() or "none"
        done = str(item.get("done_when") or item.get("done") or "").strip()
        if not done:
            done = f"Step completed: {step}"
        steps.append({"step": step, "tool_hint": hint, "done_when": done})
    if not steps:
        return None
    return {"steps": steps}


def format_plan_for_system(plan: dict[str, Any]) -> str:
    steps = plan.get("steps") or []
    lines = []
    for i, s in enumerate(steps, 1):
        lines.append(
            f"{i}. {s.get('step')} "
            f"[tool_hint={s.get('tool_hint')}] "
            f"(done when: {s.get('done_when')})"
        )
    return PLAN_SYSTEM_PREFIX.format(plan_text="\n".join(lines))


def _emit_plan(plan: dict[str, Any], *, source: str, note: str = "") -> dict[str, Any]:
    global _current_plan, _plan_note
    out = {
        "steps": list(plan.get("steps") or []),
        "source": source,
        "note": note or "",
    }
    _current_plan = out
    _plan_note = note or ""
    if _on_plan is not None:
        try:
            _on_plan(dict(out))
        except Exception:
            pass
    return out


def plan_via_local(
    provider,
    history: list[ChatMessage],
    *,
    tools: list | None = None,
) -> Optional[dict[str, Any]]:
    """Cache-safe local planner: same message 0 + same tools; append plan instruction."""
    from tools.registry import active_tool_schemas

    schemas = tools if tools is not None else active_tool_schemas()
    # Append planning instruction after user message (do not touch message 0).
    history.append(ChatMessage(role="system", content=PLANNING_INSTRUCTION))
    try:
        response = provider.chat(
            history,
            tools=schemas,
            enable_thinking=True,
        )
    except Exception as exc:
        logger.info("local planner call failed: %s", type(exc).__name__)
        # Pop planning instruction
        if history and history[-1].role == "system" and history[-1].content == PLANNING_INSTRUCTION:
            history.pop()
        return None

    content = response.content or ""
    # Ignore tool calls — parse JSON from content only.
    plan = parse_plan_json(content)
    if plan is None and getattr(response, "tool_calls", None):
        # Retry once: remind JSON-only
        history.append(
            ChatMessage(
                role="system",
                content="Previous reply called tools; reply with plan JSON only, no tool calls.",
            )
        )
        try:
            response2 = provider.chat(
                history,
                tools=schemas,
                enable_thinking=True,
            )
            plan = parse_plan_json(response2.content or "")
        except Exception:
            plan = None
        # Remove retry nudge
        if history and "plan JSON only" in (history[-1].content or ""):
            history.pop()

    # Remove planning instruction (and any stray assistant) — keep prefix cacheable.
    while history and history[-1].role == "system" and (
        history[-1].content == PLANNING_INSTRUCTION
        or "plan JSON only" in (history[-1].content or "")
    ):
        history.pop()

    return plan


def plan_via_groq(user_request: str) -> tuple[Optional[dict[str, Any]], str]:
    """Groq planner. Returns (plan, note). note set on fallback/error."""
    try:
        from llm.groq.provider import (
            GroqAuthError,
            GroqConfigError,
            GroqHttpError,
            GroqProvider,
            GroqQuotaError,
        )
        from security.groq_key import has_key

        if not has_key():
            return None, "Groq key not saved; using local planner."
        prov = GroqProvider(timeout=20.0)
        resp = prov.plan(user_request)
        plan = parse_plan_json(resp.content or "")
        if plan is None:
            return None, "Groq plan unreadable; using local planner."
        return plan, ""
    except GroqQuotaError:
        return None, "Groq quota hit; planning on this PC instead."
    except (GroqAuthError, GroqConfigError, GroqHttpError) as exc:
        return None, f"Groq planner failed ({type(exc).__name__}); using local planner."
    except Exception as exc:
        logger.info("groq planner error: %s", type(exc).__name__)
        return None, "Groq planner error; using local planner."


def maybe_attach_plan(
    provider,
    history: list[ChatMessage],
    question: str,
    *,
    tools: list | None = None,
) -> Optional[dict[str, Any]]:
    """If planner mode on and needs_plan, produce a plan and append system message."""
    reset_plan_turn()
    mode = effective_planner_mode()
    if mode == "off":
        return None
    if not needs_plan(question):
        return None

    plan: Optional[dict[str, Any]] = None
    note = ""
    source = "local"

    if mode == "groq":
        plan, note = plan_via_groq(question)
        if plan is not None:
            source = "groq"
        else:
            source = "local"
            plan = plan_via_local(provider, history, tools=tools)
    else:
        plan = plan_via_local(provider, history, tools=tools)

    if plan is None:
        return None

    history.append(ChatMessage(role="system", content=format_plan_for_system(plan)))
    return _emit_plan(plan, source=source, note=note)


def should_run_finish_guard() -> bool:
    return _current_plan is not None and not _finish_guard_fired


def finish_guard_message() -> ChatMessage:
    return ChatMessage(role="system", content=FINISH_GUARD_INSTRUCTION)


def plan_ui_payload() -> Optional[dict[str, Any]]:
    """Checklist payload for the UI (steps + done flags)."""
    if not _current_plan:
        return None
    steps = []
    for s in _current_plan.get("steps") or []:
        steps.append(
            {
                "step": s.get("step"),
                "tool_hint": s.get("tool_hint"),
                "done_when": s.get("done_when"),
                "done": bool(s.get("done")),
            }
        )
    return {
        "steps": steps,
        "source": _current_plan.get("source"),
        "note": _plan_note,
        "finish_guard_fired": _finish_guard_fired,
    }


def apply_finish_guard_done_flags(text: str) -> None:
    """Best-effort: mark steps done when the guard text affirms them."""
    if not _current_plan:
        return
    low = (text or "").lower()
    for s in _current_plan.get("steps") or []:
        # Mark done if "done"/"yes"/"complete" appears near the step wording.
        step = str(s.get("step") or "").lower()
        token = step[:24] if step else ""
        if not token:
            continue
        if token in low and re.search(
            r"\b(done|complete|yes|satisfied|met)\b", low
        ):
            s["done"] = True
        # Also: numbered "1. done" style
    # If the model clearly finished all, mark all done.
    if re.search(r"\ball\s+(steps?\s+)?(are\s+)?(done|complete|satisfied)\b", low):
        for s in _current_plan.get("steps") or []:
            s["done"] = True
