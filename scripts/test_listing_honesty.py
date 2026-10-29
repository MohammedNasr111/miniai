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
        maybe_correct_listing_answer,
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

    # General listing honesty: hallucinated name removed; real kept; prose untouched
    general_listing = [
        {"name": "alpha.txt", "type": "file", "size_bytes": 10},
        {"name": "beta.txt", "type": "file", "size_bytes": 20},
        {"name": "Reports", "type": "dir"},
    ]
    td2 = Path(tempfile.mkdtemp(prefix="miniai_list_gen_"))
    tx2 = td2 / "g.jsonl"
    tx2.write_text(
        json.dumps(
            {
                "type": "tool_call",
                "name": "list_directory",
                "args": {"path": "C:\\tmp"},
                "result": json.dumps(general_listing),
                "outcome": "ok",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mixed = (
        "The folder has `alpha.txt` and `ghost.bin` plus Reports. "
        "Nothing else to note about the weather."
    )
    cleaned, gmeta = maybe_correct_listing_answer(
        "What is in C:\\tmp?",
        mixed,
        transcript=_FakeTx(tx2),
    )
    check("gen_corrected", bool(gmeta and gmeta.get("corrected")), str(gmeta))
    check("gen_keeps_real", "alpha.txt" in cleaned, cleaned)
    check("gen_removes_fake", "ghost.bin" not in cleaned, cleaned)
    check(
        "gen_note",
        "weren't in the folder listing" in cleaned or "Removed" in cleaned,
        cleaned,
    )
    prose = "The weather looks fine today."
    same, gmeta2 = maybe_correct_listing_answer(
        "What is in C:\\tmp?",
        prose,
        transcript=_FakeTx(tx2),
    )
    check("gen_prose_untouched", same == prose and gmeta2 is None, str(gmeta2))

    # Two-turn chat: turn 1 listed Downloads; turn 2 declined create on Desktop.
    # Honesty must NOT use the prior turn's listing to strip test-note.txt.
    td3 = Path(tempfile.mkdtemp(prefix="miniai_list_2turn_"))
    tx3 = td3 / "two.jsonl"
    downloads_listing = [
        {"name": "report.pdf", "type": "file", "size_bytes": 1000, "size": "1000 B"},
        {"name": "photo.png", "type": "file", "size_bytes": 2000, "size": "2.0 KB"},
    ]
    tx3.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "run_start",
                        "user_prompt": "(chat session)",
                        "model": "test",
                        "system_prompt": "",
                    }
                ),
                json.dumps(
                    {
                        "type": "user_turn",
                        "user_prompt": "What is in my Downloads?",
                    }
                ),
                json.dumps(
                    {
                        "type": "tool_call",
                        "name": "list_directory",
                        "args": {"path": r"C:\Users\me\Downloads"},
                        "result": json.dumps(downloads_listing),
                        "outcome": "ok",
                    }
                ),
                json.dumps(
                    {
                        "type": "final",
                        "raw": "Downloads has report.pdf and photo.png.",
                        "shown": "Downloads has report.pdf and photo.png.",
                    }
                ),
                json.dumps(
                    {
                        "type": "user_turn",
                        "user_prompt": (
                            "Create a file called test-note.txt on my Desktop "
                            "saying hello."
                        ),
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    q2 = "Create a file called test-note.txt on my Desktop saying hello."
    declined = (
        "You declined, so nothing was changed. I did not create `test-note.txt` "
        "on your Desktop."
    )
    kept, meta2 = maybe_correct_listing_answer(
        q2, declined, transcript=_FakeTx(tx3)
    )
    check("two_turn_no_correct", meta2 is None, str(meta2))
    check("two_turn_keeps_name", "test-note.txt" in kept, kept)
    check(
        "two_turn_no_removed_note",
        "Removed" not in kept and "weren't in the folder listing" not in kept,
        kept,
    )

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
