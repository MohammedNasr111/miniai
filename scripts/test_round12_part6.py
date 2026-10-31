"""Round 12 Part 6 — relative create paths resolve to Desktop (not the repo)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def test_resolve_create_relative_to_desktop() -> None:
    from config.paths import install_eval_user_folders, set_eval_user_folders
    from tools.filesystem.fs_tools import resolve_create_path, resolve_fs_path

    with tempfile.TemporaryDirectory(prefix="miniai_r12p6_") as td:
        mapped = install_eval_user_folders(Path(td))
        try:
            rel = resolve_create_path("Inbox")
            _check(
                "relative_to_eval_desktop",
                rel == mapped["Desktop"] / "Inbox",
                str(rel),
            )
            nested = resolve_create_path("notes\\todo.txt")
            _check(
                "nested_relative_to_desktop",
                nested == mapped["Desktop"] / "notes" / "todo.txt",
                str(nested),
            )
            desktop_pref = resolve_create_path("Desktop\\Other")
            _check(
                "desktop_prefix_unchanged",
                desktop_pref == mapped["Desktop"] / "Other",
                str(desktop_pref),
            )
            docs = resolve_create_path("Documents\\x.txt")
            _check(
                "documents_prefix_unchanged",
                docs == mapped["Documents"] / "x.txt",
                str(docs),
            )
            # resolve_fs_path alone still leaves bare relative as relative
            bare = resolve_fs_path("bare_rel")
            _check(
                "resolve_fs_path_still_relative",
                not bare.is_absolute(),
                str(bare),
            )
            # Must not resolve under the MiniAI repo
            _check(
                "not_under_repo",
                PROJECT_ROOT not in rel.parents and rel != PROJECT_ROOT / "Inbox",
                f"rel={rel} root={PROJECT_ROOT}",
            )
        finally:
            set_eval_user_folders(None)


def test_create_folder_message_full_path() -> None:
    from config.paths import install_eval_user_folders, set_eval_user_folders
    from tools.filesystem import fs_tools

    with tempfile.TemporaryDirectory(prefix="miniai_r12p6c_") as td:
        mapped = install_eval_user_folders(Path(td))
        expected = mapped["Desktop"] / "r12p6_folder"
        try:
            with mock.patch.object(fs_tools, "check_permission", return_value=None), mock.patch(
                "security.gate.check_permission", return_value=None
            ):
                # Also patch assert_not_protected via the module used
                msg = fs_tools.create_folder("r12p6_folder")
            _check(
                "create_folder_msg_full",
                str(expected) in msg and expected.is_dir(),
                msg,
            )
            msg2 = None
            with mock.patch.object(fs_tools, "check_permission", return_value=None):
                msg2 = fs_tools.create_file("r12p6_note.txt", "hi")
            expected_file = mapped["Desktop"] / "r12p6_note.txt"
            _check(
                "create_file_msg_full",
                str(expected_file) in (msg2 or "") and expected_file.is_file(),
                msg2 or "",
            )
            with mock.patch.object(fs_tools, "check_permission", return_value=None):
                msg3 = fs_tools.write_file("r12p6_w.txt", "yo")
            expected_w = mapped["Desktop"] / "r12p6_w.txt"
            _check(
                "write_file_msg_full",
                str(expected_w) in msg3 and expected_w.is_file(),
                msg3,
            )
        finally:
            set_eval_user_folders(None)


def test_eval_redirect_keeps_off_real_desktop() -> None:
    from config.paths import (
        install_eval_user_folders,
        real_user_folders,
        set_eval_user_folders,
    )
    from tools.filesystem.fs_tools import resolve_create_path

    real = real_user_folders()["Desktop"]
    with tempfile.TemporaryDirectory(prefix="miniai_r12p6e_") as td:
        mapped = install_eval_user_folders(Path(td))
        try:
            got = resolve_create_path("stay_off_real")
            _check(
                "eval_not_real_desktop",
                str(mapped["Desktop"]) in str(got)
                and str(real) not in str(got),
                f"got={got} real={real}",
            )
        finally:
            set_eval_user_folders(None)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_resolve_create_relative_to_desktop()
    test_create_folder_message_full_path()
    test_eval_redirect_keeps_off_real_desktop()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
