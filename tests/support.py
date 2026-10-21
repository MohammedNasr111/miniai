"""Test helpers: isolate every write from the real memory and vector stores.

Call use_temp_data() at the very top of a test script, BEFORE importing any
project module that reads config/settings (or memory/vector code). That sets
MINIAI_MEMORY_DB and MINIAI_VECTOR_DB to paths under a fresh temp directory.
"""

from __future__ import annotations

import builtins
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_MEMORY_DB = (PROJECT_ROOT / "memory" / "database" / "miniai_memory.db").resolve()
REAL_VECTOR_DB = (PROJECT_ROOT / "memory" / "vector" / "lancedb").resolve()


def use_temp_data() -> Path:
    """Create a temp dir, point both store env vars at it, return the dir.

    Prefer calling this before `config.settings` is imported. If settings is
    already loaded (e.g. eval readiness probe), refresh its path attributes
    so assert_not_real_data() still sees the temp stores.
    """
    root = Path(tempfile.mkdtemp(prefix="miniai_test_"))
    memory_path = root / "miniai_memory.db"
    vector_path = root / "lancedb"
    os.environ["MINIAI_MEMORY_DB"] = str(memory_path)
    os.environ["MINIAI_VECTOR_DB"] = str(vector_path)
    # Refresh module-level paths if settings was imported early.
    import sys

    mod = sys.modules.get("config.settings")
    if mod is not None:
        mod.MEMORY_DB_PATH = Path(memory_path)
        mod.VECTOR_DB_PATH = Path(vector_path)
    print(f"[tests.support] temp data root={root}")
    print(f"[tests.support] MINIAI_MEMORY_DB={memory_path}")
    print(f"[tests.support] MINIAI_VECTOR_DB={vector_path}")
    return root


def assert_not_real_data() -> None:
    """Raise if either effective store path is the real production location."""
    # Import here so callers can set env via use_temp_data() first.
    from config import settings

    memory = Path(settings.MEMORY_DB_PATH).resolve()
    vector = Path(settings.VECTOR_DB_PATH).resolve()
    if memory == REAL_MEMORY_DB:
        raise RuntimeError(
            f"Refusing to run: MEMORY_DB_PATH resolves to the real store "
            f"({REAL_MEMORY_DB}). Call use_temp_data() before importing "
            f"project modules."
        )
    if vector == REAL_VECTOR_DB:
        raise RuntimeError(
            f"Refusing to run: VECTOR_DB_PATH resolves to the real store "
            f"({REAL_VECTOR_DB}). Call use_temp_data() before importing "
            f"project modules."
        )


@contextmanager
def answer_by_action(
    mapping: dict[str, str],
    default: str = "no",
) -> Iterator[list[tuple[str, str, str]]]:
    """Answer approval prompts from the latest ``Action: <name>``.

    Patches ``builtins.input`` (ConsoleApprover still calls ``input()``) and
    also wraps the active Approver so WebviewApprover / future approvers are
    covered. Unmapped actions get ``default`` (usually ``\"no\"``). Yields a
    log of ``(action, prompt, answer)`` tuples.
    """
    from security.approver import Approver, get_approver, set_approver

    last_action: dict[str, str | None] = {"name": None}
    log: list[tuple[str, str, str]] = []
    real_print = builtins.print

    def _note_action_from_text(text: str) -> None:
        for line in text.splitlines():
            if line.startswith("Action: "):
                last_action["name"] = line[len("Action: ") :].strip()

    def capturing_print(*args, **kwargs):
        sep = kwargs.get("sep", " ")
        text = sep.join(str(a) for a in args)
        _note_action_from_text(text)
        return real_print(*args, **kwargs)

    def smart_input(prompt: str = "") -> str:
        action = last_action["name"] or ""
        answer = mapping.get(action, default)
        log.append((action, prompt, answer))
        real_print(f"[INPUT] action={action!r} prompt={prompt!r} -> {answer!r}")
        return answer

    class MappingApprover(Approver):
        """Delegates display to the previous approver's prints via banner; answers from mapping."""

        def ask_yes_no(self, action: str, description: str, banner: str) -> bool:
            _note_action_from_text(banner or "")
            if banner:
                capturing_print(banner, end="" if banner.endswith("\n") else "\n")
            prompt = "Allow? [yes/no]: "
            answer = smart_input(prompt)
            return answer.strip().lower() == "yes"

        def ask_typed(self, action: str, description: str, banner: str) -> str:
            _note_action_from_text(banner or "")
            if banner:
                capturing_print(banner, end="" if banner.endswith("\n") else "\n")
            prompt = f"Type {action} to approve, anything else denies: "
            return smart_input(prompt)

        def ask_app_read(self, exe: str, title: str, extra: str):
            _note_action_from_text(extra or "")
            if extra:
                capturing_print(extra, end="" if extra.endswith("\n") else "\n")
            prompt = (
                "Type 'session' (until you exit), 'always' (saved to your trusted "
                "apps), or anything else to refuse: "
            )
            # desktop_read_window is the Action: line in extra
            action = last_action["name"] or "desktop_read_window"
            answer = mapping.get(action, default)
            log.append((action, prompt, answer))
            real_print(f"[INPUT] action={action!r} prompt={prompt!r} -> {answer!r}")
            if answer in ("session", "always"):
                return answer
            return "refuse"

        def ask_continue(self, message: str) -> bool:
            capturing_print("\n[PERMISSION REQUIRED - CONFIRM]")
            capturing_print("Action: desktop_task_continue")
            capturing_print(message)
            prompt = "Allow? [yes/no]: "
            answer = smart_input(prompt)
            return answer.strip().lower() == "yes"

    previous = set_approver(MappingApprover())
    try:
        with (
            patch("builtins.print", side_effect=capturing_print),
            patch("builtins.input", side_effect=smart_input),
        ):
            yield log
    finally:
        set_approver(previous)
