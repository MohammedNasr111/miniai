"""Offline checks for Recycle Bin deletes, overwrite backups, protected paths.

All mutating work uses a temp folder outside the project tree.
"""

from __future__ import annotations

from tests.support import assert_not_real_data, use_temp_data

use_temp_data()

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from security.gate import reset_session
from security.protected_paths import PROJECT_ROOT, PROTECTED_MESSAGE
from tools.filesystem import fs_tools
from tools.filesystem.fs_tools import create_file, delete_file, write_file

FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _outside_repo_temp() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory(prefix="miniai_recover_")
    resolved = Path(tmp.name).resolve()
    root = PROJECT_ROOT.resolve()
    assert resolved != root and root not in resolved.parents
    return tmp


def _recycle_bin_has_content(marker: str) -> Path | None:
    """Find a $Recycle.Bin file whose bytes contain marker (not permanently removed).

    Method: walk ``X:\\$Recycle.Bin`` for the user's SID folders and search file
    contents for the unique marker. Shell.Application NameSpace(10) name lookup
    is unreliable for temp-folder deletes under this environment.
    """
    needle = marker.encode("utf-8")
    for drive in "CDEFGHIJ":
        root = Path(f"{drive}:/$Recycle.Bin")
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    # Recycle payloads are small for our tests; cap read size.
                    data = path.read_bytes()[:65536]
                except OSError:
                    continue
                if needle in data:
                    return path
        except OSError:
            continue
    return None


def _remove_recycle_payload(path: Path | None) -> None:
    """Best-effort cleanup of the recycled payload file after the test."""
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass
    # Companion $I metadata file often sits beside $R*
    try:
        sibling = path.parent / ("$I" + path.name[2:])
        if sibling.exists():
            sibling.unlink()
    except OSError:
        pass


def _yes_input(prompt: str = "") -> str:
    return "yes"


def test_1_recycle_bin() -> None:
    reset_session()
    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "recycle_me.txt"
        unique = f"miniai-recycle-marker-{os.getpid()}-{os.urandom(4).hex()}"
        path.write_text(unique, encoding="utf-8")
        with patch("builtins.input", side_effect=_yes_input):
            with patch("sys.stdout", new=io.StringIO()):
                msg = delete_file(str(path))
        gone = not path.exists()
        payload = _recycle_bin_has_content(unique)
        in_bin = payload is not None
        ok = (
            gone
            and in_bin
            and "Recycle Bin" in msg
            and "restored" in msg
        )
        report(
            "1",
            ok,
            f"gone={gone} in_bin={in_bin} payload={payload!s} msg={msg!r} "
            f"verify=$Recycle.Bin content search for unique marker",
        )
        _remove_recycle_payload(payload)


def test_2_send2trash_failure() -> None:
    reset_session()
    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "keep_me.txt"
        path.write_text("keep", encoding="utf-8")
        with patch.object(fs_tools, "send2trash", side_effect=OSError("boom")):
            with patch("builtins.input", side_effect=_yes_input):
                with patch("sys.stdout", new=io.StringIO()):
                    raised = None
                    try:
                        delete_file(str(path))
                    except Exception as exc:
                        raised = exc
        still = path.exists() and path.read_text(encoding="utf-8") == "keep"
        ok = still and raised is not None and "Recycle Bin" in str(raised)
        report("2", ok, f"still={still} raised={raised!r}")


def test_3_write_backup() -> None:
    reset_session()
    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "overwrite_me.txt"
        path.write_text("OLD_CONTENT", encoding="utf-8")
        with patch("builtins.input", side_effect=_yes_input):
            with patch("sys.stdout", new=io.StringIO()):
                msg = write_file(str(path), "NEW_CONTENT")
        new_ok = path.read_text(encoding="utf-8") == "NEW_CONTENT"
        # Parse backup path from message.
        marker = "Backup saved at "
        backup_path = None
        if marker in msg:
            backup_path = Path(msg.split(marker, 1)[1].rstrip("."))
        backup_ok = (
            backup_path is not None
            and backup_path.exists()
            and backup_path.read_text(encoding="utf-8") == "OLD_CONTENT"
            and "MiniAI" in str(backup_path)
            and "backups" in str(backup_path)
        )
        ok = new_ok and backup_ok
        report(
            "3",
            ok,
            f"new_ok={new_ok} backup={backup_path!s} "
            f"backup_content_ok={backup_ok} msg={msg!r}",
        )
        if backup_path is not None and backup_path.exists():
            backup_path.unlink()


def test_4_backup_failure() -> None:
    reset_session()
    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "no_write.txt"
        path.write_text("ORIGINAL", encoding="utf-8")
        with patch.object(
            fs_tools, "backup_existing_file", side_effect=OSError("disk full")
        ):
            with patch("builtins.input", side_effect=_yes_input):
                with patch("sys.stdout", new=io.StringIO()):
                    raised = None
                    try:
                        write_file(str(path), "SHOULD_NOT_APPEAR")
                    except Exception as exc:
                        raised = exc
        unchanged = path.read_text(encoding="utf-8") == "ORIGINAL"
        ok = unchanged and raised is not None and "Backup failed" in str(raised)
        report("4", ok, f"unchanged={unchanged} raised={raised!r}")


def _expect_protected(label: str, call, gate_hits: list[str]) -> bool:
    before = len(gate_hits)
    try:
        call()
        return False
    except Exception as exc:
        return PROTECTED_MESSAGE in str(exc) and len(gate_hits) == before


def test_5_protected() -> None:
    reset_session()
    gate_hits: list[str] = []

    def _tracking_input(prompt: str = "") -> str:
        gate_hits.append(prompt)
        return "yes"

    # ..\miniai\... from inside the repo cwd resolves back into the project.
    rel = os.path.join("..", PROJECT_ROOT.name, "security", "gate.py")
    mixed = str(PROJECT_ROOT).swapcase() + os.sep + "ARCHITECTURE.md"
    bp_file = str(PROJECT_ROOT / "browser_profile" / "_prot_test.txt")
    results: dict[str, bool] = {}

    with patch("builtins.input", side_effect=_tracking_input):
        with patch("sys.stdout", new=io.StringIO()):
            # Inside the repo
            results["repo-create"] = _expect_protected(
                "repo-create",
                lambda: create_file(str(PROJECT_ROOT / "_prot_create.txt"), "x"),
                gate_hits,
            )
            results["repo-write"] = _expect_protected(
                "repo-write",
                lambda: write_file(str(PROJECT_ROOT / "ARCHITECTURE.md"), "x"),
                gate_hits,
            )
            results["repo-delete"] = _expect_protected(
                "repo-delete",
                lambda: delete_file(str(PROJECT_ROOT / "ARCHITECTURE.md")),
                gate_hits,
            )
            # Via .. path
            results["dotdot-write"] = _expect_protected(
                "dotdot-write", lambda: write_file(rel, "x"), gate_hits
            )
            results["dotdot-delete"] = _expect_protected(
                "dotdot-delete", lambda: delete_file(rel), gate_hits
            )
            # Different letter case
            results["case-write"] = _expect_protected(
                "case-write", lambda: write_file(mixed, "x"), gate_hits
            )
            results["case-delete"] = _expect_protected(
                "case-delete", lambda: delete_file(mixed), gate_hits
            )
            # browser_profile
            results["bp-create"] = _expect_protected(
                "bp-create", lambda: create_file(bp_file, "x"), gate_hits
            )
            results["bp-write"] = _expect_protected(
                "bp-write", lambda: write_file(bp_file, "x"), gate_hits
            )
            results["bp-delete"] = _expect_protected(
                "bp-delete", lambda: delete_file(bp_file), gate_hits
            )

    ok = all(results.values()) and len(gate_hits) == 0
    report("5", ok, f"results={results!r} gate_hits={len(gate_hits)} rel={rel!r}")


def test_6_drive_type_refused() -> None:
    """Patched GetDriveTypeW 2 (removable) and 4 (network) -> refuse, no gate."""
    reset_session()
    gate_hits: list[str] = []

    def _tracking_input(prompt: str = "") -> str:
        gate_hits.append(prompt)
        return "yes"

    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "on_weird_drive.txt"
        path.write_text("stay", encoding="utf-8")
        results: dict[str, bool] = {}
        for label, drive_type in (("removable", 2), ("network", 4)):
            gate_hits.clear()
            with patch.object(fs_tools, "get_drive_type", return_value=drive_type):
                with patch("builtins.input", side_effect=_tracking_input):
                    with patch("sys.stdout", new=io.StringIO()):
                        raised = None
                        try:
                            delete_file(str(path))
                        except Exception as exc:
                            raised = exc
            intact = path.exists() and path.read_text(encoding="utf-8") == "stay"
            results[label] = (
                intact
                and raised is not None
                and "cannot be safely sent to the Recycle Bin" in str(raised)
                and len(gate_hits) == 0
            )
        ok = all(results.values())
        report("6", ok, f"results={results!r}")


def test_7_large_file_refused() -> None:
    """Sparse ~501 MB file -> refused, gate not reached, file intact."""
    reset_session()
    gate_hits: list[str] = []

    def _tracking_input(prompt: str = "") -> str:
        gate_hits.append(prompt)
        return "yes"

    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "big_sparse.bin"
        # Sparse-ish file: seek past 501 MiB without writing 501 MiB of zeros.
        size = 501 * 1024 * 1024
        with open(path, "wb") as handle:
            handle.seek(size - 1)
            handle.write(b"\0")
        assert path.stat().st_size >= size
        with patch("builtins.input", side_effect=_tracking_input):
            with patch("sys.stdout", new=io.StringIO()):
                raised = None
                try:
                    delete_file(str(path))
                except Exception as exc:
                    raised = exc
        intact = path.exists() and path.stat().st_size >= size
        ok = (
            intact
            and raised is not None
            and "larger than 500 MB" in str(raised)
            and len(gate_hits) == 0
        )
        report(
            "7",
            ok,
            f"intact={intact} size={path.stat().st_size if path.exists() else None} "
            f"gate_hits={len(gate_hits)} raised={raised!r}",
        )


def test_8_write_create_prompt() -> None:
    """write_file on a missing path prompts 'Create file (did not exist)'."""
    reset_session()
    prompts: list[str] = []

    def _capture(prompt: str = "") -> str:
        # gate prints description before input; capture via patching print is hard —
        # re-check by reading description passed to check_permission.
        return "yes"

    with _outside_repo_temp() as tmp:
        path = Path(tmp) / "brand_new.txt"
        assert not path.exists()
        captured: list[str] = []

        real_check = fs_tools.check_permission

        def _wrap(action, tier, description, url=None):
            captured.append(description)
            return real_check(action, tier, description, url=url)

        with patch.object(fs_tools, "check_permission", side_effect=_wrap):
            with patch("builtins.input", side_effect=_capture):
                with patch("sys.stdout", new=io.StringIO()):
                    msg = write_file(str(path), "hello")
        ok = (
            path.exists()
            and path.read_text(encoding="utf-8") == "hello"
            and any(
                d.startswith("Create file (did not exist):") for d in captured
            )
            and not any(d.startswith("Overwrite existing file:") for d in captured)
        )
        report("8", ok, f"captured={captured!r} msg={msg!r}")


def main() -> None:
    assert_not_real_data()
    test_1_recycle_bin()
    test_2_send2trash_failure()
    test_3_write_backup()
    test_4_backup_failure()
    test_5_protected()
    test_6_drive_type_refused()
    test_7_large_file_refused()
    test_8_write_create_prompt()
    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    raise SystemExit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
