"""Round 7e Part 2: verify strings state exactly what code checked."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from agent.action_claim_check import note_fs_verify_target, reset_action_claim_state
    from agent.post_action_verify import verify_create_delete

    with tempfile.TemporaryDirectory(prefix="miniai_vw_") as tmp:
        desktopish = Path(tmp) / "Desktop"
        desktopish.mkdir()
        f = desktopish / "notes.txt"
        # Never create f — simulates post-delete absence
        reset_action_claim_state()
        note_fs_verify_target("delete_file", str(f), was_dir=False)

        # Force recycle-bin name check to miss → must use Gone from wording
        with patch(
            "agent.post_action_verify._recycle_bin_has_basename", return_value=False
        ):
            meta = verify_create_delete()
        detail = meta["checks"][0]["detail"]
        check("ok_gone", meta["checks"][0]["ok"], detail)
        check(
            "gone_from_desktop",
            detail.startswith("Gone from Desktop")
            and "Recycle Bin" in detail,
            detail,
        )
        check(
            "not_claim_in_bin_alone",
            detail != "File is in the Recycle Bin",
            detail,
        )
        check(
            "checked_flag",
            meta["checks"][0].get("checked") == "path_absent",
            str(meta["checks"][0]),
        )

        # When recycle check succeeds, wording may say in the Recycle Bin
        reset_action_claim_state()
        note_fs_verify_target("delete_file", str(f), was_dir=False)
        with patch(
            "agent.post_action_verify._recycle_bin_has_basename", return_value=True
        ):
            meta2 = verify_create_delete()
        d2 = meta2["checks"][0]["detail"]
        check("in_bin_when_checked", "Recycle Bin" in d2 and "is in" in d2, d2)
        check(
            "checked_includes_bin",
            "recycle_bin_name" in str(meta2["checks"][0].get("checked")),
            str(meta2["checks"][0]),
        )

        # Create wording is exact
        reset_action_claim_state()
        made = Path(tmp) / "x.txt"
        made.write_text("hi", encoding="utf-8")
        note_fs_verify_target("create_file", str(made), was_dir=False)
        meta3 = verify_create_delete()
        check(
            "file_exists_exact",
            meta3["checks"][0]["detail"] == "File exists on disk",
            meta3["checks"][0]["detail"],
        )

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
