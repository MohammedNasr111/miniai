"""Round 11 Part 2 — plan checklist UI hooks (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    css = (PROJECT_ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    py = (PROJECT_ROOT / "app" / "webview_approver.py").read_text(encoding="utf-8")

    for token in (
        ".plan-check",
        ".plan-check-item",
        ".plan-tick",
        "var(--verdigris)",
    ):
        _check(f"css:{token}", token in css)

    _check("js_showPlanChecklist", "function showPlanChecklist" in js)
    _check("js_on_plan", "on_plan:" in js or "on_plan :" in js)
    _check("js_planBox", "planBox" in js)
    _check("js_done_class", 'class="plan-check-item' in js or "plan-check-item" in js)
    _check("bridge_set_plan_hook", "set_plan_hook" in py)
    _check("bridge_on_plan_call", 'on_plan"' in py or "on_plan'" in py or '\"on_plan\"' in py or "\"on_plan\"" in py)
    _check("answer_includes_plan", '"plan": plan_payload' in py or "'plan': plan_payload" in py)

    # Placement: plan-check under ask, before trace (startRun order).
    idx_ask = js.find('ask.className = "ask"')
    idx_plan = js.find('planBox.className = "plan-check"')
    idx_trace = js.find('trace.className = "trace"')
    _check(
        "dom_order_ask_plan_trace",
        idx_ask >= 0 and idx_plan > idx_ask and idx_trace > idx_plan,
        f"ask={idx_ask} plan={idx_plan} trace={idx_trace}",
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
