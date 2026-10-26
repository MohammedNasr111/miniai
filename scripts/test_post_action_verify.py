"""Offline: post-action os.path.exists checks for create/delete (this turn)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

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

    with tempfile.TemporaryDirectory(prefix="miniai_pav_") as tmp:
        root = Path(tmp)
        f = root / "a.txt"
        f.write_text("x", encoding="utf-8")
        folder = root / "dir"
        folder.mkdir()
        gone = root / "gone.txt"
        # gone never created → delete verify: path absent

        reset_action_claim_state()
        note_fs_verify_target("create_file", str(f), was_dir=False)
        note_fs_verify_target("create_folder", str(folder), was_dir=True)
        note_fs_verify_target("delete_file", str(gone), was_dir=False)

        meta = verify_create_delete()
        check("ran", meta["ran"])
        check("passed", meta["passed"], str(meta))
        details = [c["detail"] for c in meta["checks"]]
        check("file_exists", any("File exists" in d for d in details), str(details))
        check(
            "folder_exists",
            any("Folder exists" in d for d in details),
            str(details),
        )
        check(
            "recycle_or_gone",
            any(("Recycle Bin" in d) or d.startswith("Gone from") for d in details),
            str(details),
        )

        # Fail case: create reported but file missing
        reset_action_claim_state()
        missing = root / "nope.txt"
        note_fs_verify_target("create_file", str(missing), was_dir=False)
        bad = verify_create_delete()
        check("fail_missing", bad["ran"] and not bad["passed"], str(bad))

        # Prior-turn leak: after reset, old paths must not appear
        reset_action_claim_state()
        empty = verify_create_delete()
        check("empty_after_reset", not empty["ran"], str(empty))

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
