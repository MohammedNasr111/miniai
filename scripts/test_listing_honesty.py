"""Offline: biggest-files answer must match list_directory; explicit coding slug."""

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


class _FakeTx:
    def __init__(self, path: Path) -> None:
        self.path = path


def main() -> int:
    from agent.listing_honesty import (
        is_biggest_files_question,
        maybe_correct_biggest_files_answer,
    )
    from agent.research_pipeline import is_compare_question
    from tools.code.project_discover import ensure_task_slug_folder

    check(
        "is_biggest",
        is_biggest_files_question(
            'What are the 10 biggest files in C:\\tmp? Call list_directory'
        ),
    )
    check(
        "not_compare_local",
        not is_compare_question(
            "What are the 10 biggest files in C:\\tmp? list_directory"
        ),
    )

    listing = [
        {"name": "huge.zip", "type": "file", "size_bytes": 2_000_000, "size": "2.0 MB"},
        {"name": "big.bin", "type": "file", "size_bytes": 1_500_000, "size": "1.4 MB"},
        {"name": "setup.exe", "type": "file", "size_bytes": 900_000, "size": "879 KB"},
        {"name": "notes_large.txt", "type": "file", "size_bytes": 700_000, "size": "684 KB"},
        {"name": "archive.dat", "type": "file", "size_bytes": 500_000, "size": "488 KB"},
        {"name": "photo.png", "type": "file", "size_bytes": 400_000, "size": "391 KB"},
        {"name": "medium.txt", "type": "file", "size_bytes": 200_000, "size": "195 KB"},
        {"name": "small.txt", "type": "file", "size_bytes": 50_000, "size": "49 KB"},
        {"name": "tiny.txt", "type": "file", "size_bytes": 10_000, "size": "9.8 KB"},
        {"name": "micro.txt", "type": "file", "size_bytes": 5_000, "size": "4.9 KB"},
    ]
    td = Path(tempfile.mkdtemp(prefix="miniai_list_tx_"))
    tx_path = td / "t.jsonl"
    tx_path.write_text(
        json.dumps(
            {
                "type": "tool_call",
                "name": "list_directory",
                "args": {"path": "C:\\tmp", "sort_by": "size"},
                "result": json.dumps(listing),
                "outcome": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    bad = (
        "1. `huge.zip`\n2. `big.bin`\n3. `setup.exe`\n"
        "4. `data.log`\n5. `cache.tmp`\n6. `image.png`\n"
        "7. `video.mp4`\n8. `document.docx`\n9. `script.js`\n10. `micro.txt`\n"
        "Sources:\n- https://example.com/find-large-files\n"
    )
    fixed, meta = maybe_correct_biggest_files_answer(
        "What are the 10 biggest files in C:\\tmp?",
        bad,
        transcript=_FakeTx(tx_path),
    )
    check("corrected", bool(meta and meta.get("corrected")), str(meta))
    for name in (
        "huge.zip",
        "notes_large.txt",
        "archive.dat",
        "photo.png",
        "medium.txt",
        "small.txt",
        "tiny.txt",
        "micro.txt",
    ):
        check(f"has_{name}", name in fixed, fixed[:200])
    check("no_hallucination", "data.log" not in fixed and "cache.tmp" not in fixed)

    # Explicit slug
    from tests.support import use_temp_data

    use_temp_data()
    from tools.code.paths import workspace_dir

    slug = ensure_task_slug_folder(
        "In the workspace under the folder eval_wordcount, write a Python "
        "function that counts words, plus pytest tests."
    )
    check("explicit_slug", slug == "eval-wordcount" or slug == "eval_wordcount", f"slug={slug}")
    # Underscores preserved by slugify? slugify replaces non-alnum with -
    # eval_wordcount → eval-wordcount or eval_wordcount depending on _SLUG_RE
    check(
        "folder_exists",
        (workspace_dir() / (slug or "")).is_dir(),
        str(workspace_dir() / (slug or "")),
    )

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
