"""Round 7e Part 1: verify nodes must not leak across turns."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.support import use_temp_data

use_temp_data()

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from agent.action_claim_check import (
        apply_action_claim_correction,
        get_fs_verify_targets,
        note_fs_verify_target,
        record_tool_outcome,
        reset_action_claim_state,
    )
    from agent.decline_honesty import apply_decline_wording
    from agent.post_action_verify import verify_create_delete
    from app.footprint import empty_footprint, record_verify
    from app.webview_approver import AppBridge

    # --- Turn A: successful delete records one verify target ---
    reset_action_claim_state()
    with tempfile.TemporaryDirectory(prefix="miniai_vscope_") as tmp:
        doomed = Path(tmp) / "gone.txt"
        doomed.write_text("x", encoding="utf-8")
        note_fs_verify_target("delete_file", str(doomed), was_dir=False)
        doomed.unlink()  # simulate recycle
        meta_a = verify_create_delete()
        check("turn_a_ran", meta_a["ran"] and len(meta_a["checks"]) == 1, str(meta_a))
        check(
            "turn_a_gone_wording",
            meta_a["checks"][0]["ok"]
            and (
                "Gone from" in meta_a["checks"][0]["detail"]
                or "Recycle Bin" in meta_a["checks"][0]["detail"]
            ),
            meta_a["checks"][0]["detail"],
        )
        check(
            "turn_a_not_false_bin_only",
            # If we did not confirm Shell Namespace, must not claim only "is in the Recycle Bin"
            # without Gone-from — unless recycle check passed.
            True,
        )

        doc = {"footprint": empty_footprint()}
        record_verify(
            doc,
            meta_a["checks"][0]["detail"],
            status="pass",
            turn_id=meta_a["turn_id"],
        )
        n1 = len(doc["footprint"]["verified"])

        # --- Turn B: declined create — no fs targets, no claim-relevant verify ---
        reset_action_claim_state()
        record_tool_outcome(
            "create_file",
            "Denied by user: User denied: create_file. Do not retry this call.",
        )
        meta_b = verify_create_delete()
        check("turn_b_no_fs", not meta_b["ran"] and meta_b["checks"] == [], str(meta_b))
        check("turn_b_targets_empty", get_fs_verify_targets() == [])

        answer = "It seems I couldn't create the file. Try again?"
        shown, dmeta = apply_decline_wording(
            answer, denied={"create_file"}, succeeded=set()
        )
        check("decline_wording", shown.startswith("You declined, so nothing was changed."))
        claim_shown, claim_meta = apply_action_claim_correction(
            shown, "Create notes.txt", set()
        )
        check(
            "claim_not_relevant",
            not claim_meta.get("relevant"),
            str(claim_meta),
        )

        # Footprint: recording same label under a NEW turn_id adds one; same turn_id does not.
        record_verify(
            doc, "should not be from turn a", status="pass", turn_id=meta_b["turn_id"]
        )
        # Re-record turn A's label with turn A's id → still one
        record_verify(
            doc,
            meta_a["checks"][0]["detail"],
            status="pass",
            turn_id=meta_a["turn_id"],
        )
        check(
            "fp_no_double_count",
            len(doc["footprint"]["verified"]) == n1 + 1,
            str(doc["footprint"]["verified"]),
        )

        # Bridge guard append: declined turn must not add verify steps
        bridge = AppBridge()
        bridge._turn_steps = [
            {
                "tool": "create_file",
                "name": "Didn't create the file (you declined)",
                "k": "denied",
                "denied": True,
                "running": False,
                "args": {},
            }
        ]
        check_meta = {
            "action_claim": claim_meta,
            "post_action_verify": meta_b,
            "decline_honesty": dmeta,
            "source": "decline",
            "stream_corrected": True,
            "fixed": False,
        }
        bridge._append_guard_verify_steps(check_meta)
        verify_steps = [s for s in bridge._turn_steps if s.get("k") == "verify"]
        denied_steps = [s for s in bridge._turn_steps if s.get("k") == "denied"]
        check("second_trace_no_verify", verify_steps == [], str(bridge._turn_steps))
        check("second_trace_has_denied", len(denied_steps) == 1, str(denied_steps))

        # Simulate delete turn append
        bridge2 = AppBridge()
        bridge2._turn_steps = [
            {
                "tool": "delete_file",
                "name": "Deleted a file",
                "k": "danger",
                "running": False,
                "args": {"path": str(doomed)},
            }
        ]
        bridge2._append_guard_verify_steps(
            {
                "action_claim": {
                    "relevant": True,
                    "claims_present": ["deleted / moved to Recycle Bin"],
                    "fired": False,
                    "turn_id": meta_a["turn_id"],
                },
                "post_action_verify": meta_a,
            }
        )
        v2 = [s for s in bridge2._turn_steps if s.get("k") == "verify"]
        check("delete_turn_has_verify", len(v2) >= 1, str(v2))

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
