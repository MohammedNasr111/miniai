"""Offline: post-action os.path.exists checks for create/delete."""

from __future__ import annotations

import json
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


class _Tx:
    def __init__(self, path: Path) -> None:
        self.path = path


def main() -> int:
    from agent.post_action_verify import verify_create_delete

    with tempfile.TemporaryDirectory(prefix="miniai_pav_") as tmp:
        root = Path(tmp)
        f = root / "a.txt"
        f.write_text("x", encoding="utf-8")
        folder = root / "dir"
        folder.mkdir()
        gone = root / "gone.txt"
        # Simulate deleted: path should not exist
        tx = root / "t.jsonl"
        events = [
            {
                "type": "tool_call",
                "name": "create_file",
                "args": {"path": str(f)},
                "result": f"Created {f}",
                "outcome": "ok",
            },
            {
                "type": "tool_call",
                "name": "create_folder",
                "args": {"path": str(folder)},
                "result": f"Created folder {folder}",
                "outcome": "ok",
            },
            {
                "type": "tool_call",
                "name": "delete_file",
                "args": {"path": str(gone)},
                "result": f"Moved {gone} to the Recycle Bin.",
                "outcome": "ok",
            },
        ]
        tx.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
        )
        meta = verify_create_delete(transcript=_Tx(tx))
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
            "recycle",
            any("Recycle Bin" in d for d in details),
            str(details),
        )

        # Fail case: create reported but file missing
        missing = root / "nope.txt"
        tx2 = root / "t2.jsonl"
        tx2.write_text(
            json.dumps(
                {
                    "type": "tool_call",
                    "name": "create_file",
                    "args": {"path": str(missing)},
                    "outcome": "ok",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        bad = verify_create_delete(transcript=_Tx(tx2))
        check("fail_missing", bad["ran"] and not bad["passed"], str(bad))

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
