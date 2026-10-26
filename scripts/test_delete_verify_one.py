"""One delete verify node per path; never 'Gone from .' as the parent."""

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
    from agent.action_claim_check import (
        note_fs_verify_target,
        record_tool_outcome,
        reset_action_claim_state,
        get_fs_verify_targets,
    )
    from agent.post_action_verify import _parent_label, verify_create_delete
    from app.webview_approver import AppBridge

    # Parent label must never be "."
    check("parent_desktopish", _parent_label(r"C:\Users\x\Desktop\MyFolder") != ".")
    check(
        "parent_not_dot",
        _parent_label(r"C:\Users\x\Desktop\MyFolder") not in (".", "..", ""),
        _parent_label(r"C:\Users\x\Desktop\MyFolder"),
    )
    # Relative bare name must not yield "."
    lab = _parent_label("folder")
    check("bare_folder_not_dot", lab not in (".", ".."), lab)

    with tempfile.TemporaryDirectory(prefix="miniai_dvo_") as tmp:
        desktop = Path(tmp) / "Desktop"
        desktop.mkdir()
        folder = desktop / "TestFolder"
        folder.mkdir()
        path = str(folder)

        reset_action_claim_state()
        # Authoritative note from delete_file
        note_fs_verify_target("delete_file", path, was_dir=True)
        # Simulate the old bug: result-text parse also tried to register paths
        record_tool_outcome(
            "delete_file",
            f"Moved folder {path} to the Recycle Bin. It can be restored from there.",
        )
        # Even if something registered a bogus "folder" path, verify must dedupe.
        note_fs_verify_target("delete_file", "folder", was_dir=True)

        targets = get_fs_verify_targets()
        real = [t for t in targets if t[1].lower() not in ("folder", "file")]
        check("no_bogus_folder_target", len(real) == 1, str(targets))

        # Path gone (simulate recycle)
        import shutil

        shutil.rmtree(folder)

        with patch(
            "agent.post_action_verify._recycle_bin_has_basename", return_value=True
        ):
            meta = verify_create_delete()
        check("one_check", len(meta["checks"]) == 1, str(meta["checks"]))
        detail = meta["checks"][0]["detail"]
        check("not_gone_from_dot", "Gone from ." not in detail, detail)
        check(
            "folder_in_bin_or_desktop",
            "Folder is in the Recycle Bin" in detail
            or "Gone from Desktop" in detail,
            detail,
        )

        with patch(
            "agent.post_action_verify._recycle_bin_has_basename", return_value=False
        ):
            # Re-note after reset for Gone-from path
            reset_action_claim_state()
            note_fs_verify_target("delete_file", path, was_dir=True)
            meta2 = verify_create_delete()
        d2 = meta2["checks"][0]["detail"]
        check("gone_from_desktop", d2.startswith("Gone from Desktop"), d2)
        check("no_dot_in_gone", "Gone from ." not in d2 and "/ ." not in d2, d2)

        # UI: one verify step even if meta had two alternate details (defensive)
        bridge = AppBridge()
        bridge._turn_steps = []
        bridge._append_guard_verify_steps(
            {
                "post_action_verify": {
                    "ran": True,
                    "turn_id": "t1",
                    "checks": [
                        {
                            "ok": True,
                            "path": path,
                            "detail": "Gone from . (sent to the Recycle Bin)",
                        },
                        {
                            "ok": True,
                            "path": path,
                            "detail": "Folder is in the Recycle Bin",
                        },
                    ],
                }
            }
        )
        verifies = [s for s in bridge._turn_steps if s.get("k") == "verify"]
        check("ui_one_node", len(verifies) == 1, str(verifies))
        check(
            "ui_skips_dot",
            "Gone from ." not in (verifies[0].get("detail") or ""),
            str(verifies),
        )

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
