"""Offline + live×2 tests for create_folder (Round 7d Part 1)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from security.gate import Tier, reset_session  # noqa: E402
from tools.filesystem.fs_tools import create_file, create_folder  # noqa: E402
from tools.filesystem.turn_context import (  # noqa: E402
    clear_turn_user_text,
    set_turn_user_text,
)
from tools.registry import TOOL_FUNCTIONS, TOOL_TIERS  # noqa: E402
from app.action_classes import TOOL_CLASS, ticket_copy  # noqa: E402
from app.footprint import empty_footprint, record_tool  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def offline() -> None:
    reset_session()
    _check(
        "registry",
        TOOL_FUNCTIONS.get("create_folder") is create_folder
        and TOOL_TIERS.get("create_folder") == Tier.CONFIRM,
        "",
    )
    _check("class_change", TOOL_CLASS.get("create_folder") == "change", "")
    tc = ticket_copy("create_folder", r"Create new folder: C:\tmp\X")
    _check("ticket_approve", tc["approve"] == "Create folder", str(tc))
    _check("ticket_deny", tc["deny"] == "Don't create", str(tc))
    _check(
        "ticket_consequence",
        "new folder" in tc["consequence"].lower(),
        tc["consequence"],
    )
    doc = {"footprint": empty_footprint()}
    record_tool(doc, "create_folder", {"path": r"C:\tmp\X"}, ok=True)
    lab = doc["footprint"]["changed"][-1]["label"]
    _check("footprint_label", lab.startswith("Created folder"), lab)

    with tempfile.TemporaryDirectory(prefix="miniai_cf_") as tmp:
        root = Path(tmp).resolve()
        folder = root / "Test Folder A"
        prompts: list[str] = []

        def _gate(**kwargs):  # type: ignore[no-untyped-def]
            prompts.append(kwargs.get("action") or "")
            return None

        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            out = create_folder(str(folder))
        _check("created_isdir", folder.is_dir(), out)
        _check("prompt_create_folder", prompts == ["create_folder"], str(prompts))
        _check("msg", "Created folder" in out, out)

        # Exists → refuse before/after prompt
        prompts.clear()
        raised = False
        try:
            with patch(
                "tools.filesystem.fs_tools.check_permission", side_effect=_gate
            ):
                create_folder(str(folder))
        except FileExistsError:
            raised = True
        _check("exists_raises", raised, "")
        _check("exists_no_prompt", prompts == [], str(prompts))

        # create_file refuses extensionless when user said folder
        set_turn_user_text("Make a folder called Oops on my Desktop")
        bad = root / "Oops"
        refused = False
        try:
            with patch(
                "tools.filesystem.fs_tools.check_permission", side_effect=_gate
            ):
                create_file(str(bad), "")
        except ValueError as exc:
            refused = True
            _check(
                "refuse_msg",
                "create_folder" in str(exc).lower(),
                str(exc),
            )
        _check("refuse_extensionless", refused and not bad.exists(), "")
        clear_turn_user_text()

        # create_file with extension still ok when user said folder (e.g. note)
        set_turn_user_text("Make a folder called X and also a file notes.txt")
        notes = root / "notes.txt"
        prompts.clear()
        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            create_file(str(notes), "hi")
        _check("file_with_ext_ok", notes.is_file(), "")
        clear_turn_user_text()


def live_once(label: str, fixture: Path, name: str) -> None:
    """One live agent turn: make a folder in fixture via real model."""
    from agent.executor.guard import CallGuard
    from llm.base import ChatMessage
    from llm.lemonade.provider import LemonadeProvider
    from scripts.agent_loop import _require_lemonade, run_tool_rounds, system_prompt
    from security.approver import Approver, set_approver
    from security.gate import reset_session as gate_reset

    class YesApprover(Approver):
        def ask_yes_no(self, action: str, description: str, banner: str) -> bool:
            print(f"[AUTO-YES] {action}")
            return True

        def ask_typed(self, action: str, description: str, banner: str) -> str:
            print(f"[AUTO-TYPED] {action}")
            return action

        def ask_app_read(self, exe: str, title: str, extra: str):
            return "refuse"

        def ask_continue(self, message: str) -> bool:
            return False

    _require_lemonade()
    gate_reset()
    prev = set_approver(YesApprover())
    target = fixture / name
    if target.exists():
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    q = (
        f"Make a folder called {name} in {fixture}. "
        f"Use create_folder with path {target}. Do not use create_file."
    )
    print(f"\n=== LIVE {label}: {q} ===")
    try:
        os.environ.setdefault("MINIAI_MODEL", "Qwen3-30B-A3B-GGUF")
        provider = LemonadeProvider()
        history = [
            ChatMessage(role="system", content=system_prompt()),
            ChatMessage(role="user", content=q),
        ]
        guard = CallGuard()
        resp = run_tool_rounds(provider, history, guard, question=q)
        print(f"ANSWER[{label}]: {(resp.content or '')[:500]}")
    finally:
        set_approver(prev)
    ok = target.is_dir()
    _check(f"live_{label}_isdir", ok, str(target))
    if ok:
        try:
            shutil.rmtree(target)
        except OSError:
            pass


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    offline()
    fixture = Path(tempfile.mkdtemp(prefix="miniai_folder_live_"))
    try:
        live_once("a", fixture, "Round7dFolderA")
        live_once("b", fixture, "Round7dFolderB")
    finally:
        try:
            shutil.rmtree(fixture)
        except OSError:
            pass
    print(f"FAILURES={len(FAILURES)} {FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
