"""Round 7e Part 3: folder delete uses folder wording; ticket settle has no live buttons."""

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
    from app.action_classes import label_for, ticket_copy
    from app.footprint import empty_footprint, record_tool
    from tools.filesystem.fs_tools import delete_file

    with tempfile.TemporaryDirectory(prefix="miniai_fdel_") as tmp:
        folder = Path(tmp) / "ToDelete"
        folder.mkdir()
        prompts: list[str] = []

        def _gate(**kwargs):  # type: ignore[no-untyped-def]
            prompts.append(kwargs.get("description") or "")
            return None

        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            # Ticket copy before delete (path still a dir)
            tc = ticket_copy(
                "delete_file", f"Move folder to Recycle Bin: {folder}"
            )
            check("heading_folder", tc["heading"] == "Delete 1 folder", str(tc))
            check("approve_folder", tc["approve"] == "Delete folder", str(tc))
            check(
                "live_path_folder",
                ticket_copy("delete_file", f"Move to Recycle Bin: {folder}")[
                    "heading"
                ]
                == "Delete 1 folder",
            )

            out = delete_file(str(folder))
        check("prompt_says_folder", prompts and "folder" in prompts[0].lower(), str(prompts))
        check("result_says_folder", "folder" in out.lower(), out)
        check("gone", not folder.exists())

        lab = label_for("delete_file", done=True, args={"path": str(folder), "was_dir": True})
        check("label_folder", "folder" in lab.lower(), lab)

        doc = {"footprint": empty_footprint()}
        record_tool(
            doc,
            "delete_file",
            {"path": str(folder), "was_dir": True},
            ok=True,
        )
        flab = doc["footprint"]["changed"][-1]["label"]
        check("fp_folder", "folder" in flab.lower(), flab)

        # File wording unchanged
        tc_f = ticket_copy("delete_file", r"Move to Recycle Bin: C:\tmp\a.txt")
        check("heading_file", tc_f["heading"] == "Delete 1 file", str(tc_f))

    # JS settle contract: answered tickets must use .done and have no .btn
    js = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    check("settle_done_class", 'li.className = "ticket done"' in js)
    check(
        "reject_answered_nonce",
        "answered" in js and "return;" in js and "data-nonce" in js,
    )
    check("settle_before_reply", "Collapse BEFORE notifying Python" in js)

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
