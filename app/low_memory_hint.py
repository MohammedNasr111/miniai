"""Round 13 Part 2 — gentle low-memory / slow-speed hint (at most once/hour)."""

from __future__ import annotations

import time
from typing import Any, Optional

HINT_TEXT = (
    "Your PC is low on memory — closing big apps (browser tabs, editors) "
    "makes MiniAI faster."
)

FREE_RAM_THRESHOLD_GB = 2.5
REF_FRACTION = 0.90
HINT_COOLDOWN_S = 3600.0

_last_shown_monotonic: float = 0.0


def reset_hint_cooldown_for_tests() -> None:
    global _last_shown_monotonic
    _last_shown_monotonic = 0.0


def should_show_low_memory_hint(
    *,
    free_ram_gb: Optional[float],
    last_tok_s: Optional[float],
    ref_tok_s: Optional[float],
    now: Optional[float] = None,
    force_cooldown_clear: bool = False,
) -> tuple[bool, str]:
    """Return (show, reason). reason is for tests/logs; never user-facing secrets.

    Triggers:
    - free RAM under 2.5 GB, or
    - last predicted_per_second under 90% of the model reference tok/s.
    Rate limit: at most once per hour (process-local).
    """
    global _last_shown_monotonic
    if force_cooldown_clear:
        _last_shown_monotonic = 0.0

    t = time.monotonic() if now is None else float(now)
    if _last_shown_monotonic and (t - _last_shown_monotonic) < HINT_COOLDOWN_S:
        return False, "cooldown"

    low_ram = free_ram_gb is not None and float(free_ram_gb) < FREE_RAM_THRESHOLD_GB
    slow = False
    if (
        last_tok_s is not None
        and ref_tok_s is not None
        and float(ref_tok_s) > 0
    ):
        slow = float(last_tok_s) < float(ref_tok_s) * REF_FRACTION

    if not low_ram and not slow:
        return False, "ok"

    _last_shown_monotonic = t
    why = "low_ram" if low_ram else "slow_tok"
    if low_ram and slow:
        why = "low_ram+slow_tok"
    return True, why


def hint_payload(
    *,
    free_ram_gb: Optional[float],
    last_tok_s: Optional[float],
    ref_tok_s: Optional[float],
) -> Optional[dict[str, Any]]:
    show, reason = should_show_low_memory_hint(
        free_ram_gb=free_ram_gb,
        last_tok_s=last_tok_s,
        ref_tok_s=ref_tok_s,
    )
    if not show:
        return None
    return {"text": HINT_TEXT, "reason": reason}
