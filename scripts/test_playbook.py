"""Offline tests: playbook load limits, protected path, MINIAI_PLAYBOOK."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import answer_by_action, use_temp_data

use_temp_data()

from prompts.playbook_loader import (  # noqa: E402
    DEFAULT_PLAYBOOK,
    PLAYBOOK_MAX_CHARS,
    format_playbook_section,
    load_playbook_text,
)
from security.protected_paths import PROTECTED_MESSAGE, is_protected_path  # noqa: E402
from tools.filesystem.fs_tools import write_file  # noqa: E402

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name} - {detail}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} - {detail}")


def test_size_limit() -> None:
    td = Path(tempfile.mkdtemp())
    big = td / "big.md"
    big.write_text("# h\n" + ("x" * (PLAYBOOK_MAX_CHARS + 10)), encoding="utf-8")
    os.environ["MINIAI_PLAYBOOK"] = str(big)
    try:
        body = load_playbook_text()
        _check("oversize_loads_nothing", body == "", f"len={len(body)}")
    finally:
        os.environ.pop("MINIAI_PLAYBOOK", None)

    small = td / "small.md"
    small.write_text("# h\nPrefer official docs when sources disagree.\n", encoding="utf-8")
    os.environ["MINIAI_PLAYBOOK"] = str(small)
    try:
        body = load_playbook_text()
        section = format_playbook_section(body)
        _check(
            "small_loads",
            "Prefer official docs" in body and "Learned guidance (playbook)" in section,
            body[:60],
        )
        _check(
            "conflict_line_present",
            "If any learned guidance conflicts with the rules below, the rules below win."
            in section,
            "",
        )
    finally:
        os.environ.pop("MINIAI_PLAYBOOK", None)


def test_protected() -> None:
    path = DEFAULT_PLAYBOOK.resolve()
    _check("is_protected", is_protected_path(path), str(path))
    with answer_by_action({"write_file": "write_file"}, default="no"):
        try:
            write_file(str(path), "SHOULD_NOT_WRITE\n")
            _check("write_refused", False, "write_file succeeded")
        except Exception as exc:
            msg = str(exc)
            _check(
                "write_refused",
                PROTECTED_MESSAGE in msg or "does not modify" in msg,
                msg[:200],
            )


def test_default_hash_stable_under_temp_env() -> None:
    before = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()
    td = Path(tempfile.mkdtemp())
    alt = td / "alt.md"
    alt.write_text("# t\nTemp guidance only.\n", encoding="utf-8")
    os.environ["MINIAI_PLAYBOOK"] = str(alt)
    try:
        body = load_playbook_text()
        _check("temp_path_used", "Temp guidance only" in body, body)
    finally:
        os.environ.pop("MINIAI_PLAYBOOK", None)
    after = hashlib.sha256(DEFAULT_PLAYBOOK.read_bytes()).hexdigest()
    _check("default_unchanged", before == after, f"{before} vs {after}")


def test_system_prompt_order() -> None:
    from scripts.agent_loop import system_prompt

    td = Path(tempfile.mkdtemp())
    pb = td / "pb.md"
    pb.write_text("# h\nUse multiple sources before concluding.\n", encoding="utf-8")
    os.environ["MINIAI_PLAYBOOK"] = str(pb)
    try:
        sp = system_prompt()
        i_play = sp.find("Learned guidance (playbook)")
        i_untrust = sp.find("<<<BEGIN UNTRUSTED WEB CONTENT>>>")
        i_conflict = sp.find(
            "If any learned guidance conflicts with the rules below, the rules below win."
        )
        _check(
            "playbook_before_untrusted",
            i_play != -1 and i_untrust != -1 and i_play < i_untrust,
            f"play={i_play} untrust={i_untrust}",
        )
        _check(
            "conflict_after_playbook_before_rules",
            i_conflict != -1 and i_play < i_conflict < i_untrust,
            f"play={i_play} conflict={i_conflict} untrust={i_untrust}",
        )
    finally:
        os.environ.pop("MINIAI_PLAYBOOK", None)


def main() -> int:
    test_size_limit()
    test_protected()
    test_default_hash_stable_under_temp_env()
    test_system_prompt_order()
    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
