"""Offline regression: move_file creates parent dirs, refuses overwrite/protected."""

from __future__ import annotations

from tests.support import use_temp_data

use_temp_data()

import tempfile
from pathlib import Path
from unittest.mock import patch

from security.gate import reset_session
from security.protected_paths import PROJECT_ROOT, PROTECTED_MESSAGE
from tools.filesystem.fs_tools import move_file

FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    reset_session()
    with tempfile.TemporaryDirectory(prefix="miniai_move_") as tmp:
        root = Path(tmp).resolve()
        assert PROJECT_ROOT.resolve() not in root.parents
        src = root / "a.txt"
        src.write_text("hello\n", encoding="utf-8")
        dest = root / "pdfs" / "a.txt"

        with patch("tools.filesystem.fs_tools.check_permission", return_value=None):
            msg = move_file(str(src), str(dest))
        report(
            "move_ok",
            dest.is_file() and not src.exists() and "Moved" in msg,
            f"msg={msg!r} dest_exists={dest.is_file()} src_gone={not src.exists()}",
        )

        # Overwrite refuse
        other = root / "b.txt"
        other.write_text("x\n", encoding="utf-8")
        dest.write_text("kept\n", encoding="utf-8")
        raised = False
        try:
            with patch("tools.filesystem.fs_tools.check_permission", return_value=None):
                move_file(str(other), str(dest))
        except FileExistsError:
            raised = True
        report(
            "no_overwrite",
            raised and other.exists() and dest.read_text(encoding="utf-8") == "kept\n",
            f"raised={raised}",
        )

        # Protected path refuse before prompt
        gate_hits = []

        def _gate(**kwargs):  # type: ignore[no-untyped-def]
            gate_hits.append(kwargs.get("action"))

        prot = PROJECT_ROOT / "ARCHITECTURE.md"
        try:
            with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
                move_file(str(prot), str(root / "stolen.md"))
            ok = False
            detail = "did not raise"
        except Exception as exc:
            ok = PROTECTED_MESSAGE.split()[0].lower() in str(exc).lower() or "protected" in str(exc).lower() or "MiniAI" in str(exc)
            detail = str(exc)[:200]
        report("protected_refused", ok and not gate_hits, detail)

    if FAILURES:
        raise SystemExit(1)
    print("All move_file checks passed.")


if __name__ == "__main__":
    main()
