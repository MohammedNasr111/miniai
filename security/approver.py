"""Approver interface: display prompts and collect answers only.

Decision logic (taint, typed rules, provenance, TYPED_ALWAYS_ACTIONS,
protected paths) stays in security.gate. The active approver is swapped
for the app window (WebviewApprover) without changing the gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, Optional

AppReadAnswer = Literal["session", "always", "refuse"]


class Approver(ABC):
    @abstractmethod
    def ask_yes_no(self, action: str, description: str, banner: str) -> bool:
        """Show a yes/no approval; return True only if the user said yes."""

    @abstractmethod
    def ask_typed(self, action: str, description: str, banner: str) -> str:
        """Show a typed-name approval; return the raw string the user typed."""

    @abstractmethod
    def ask_app_read(self, exe: str, title: str, extra: str) -> AppReadAnswer:
        """Ask whether MiniAI may read a desktop app window."""

    @abstractmethod
    def ask_continue(self, message: str) -> bool:
        """Ask whether to continue a desktop task after user input."""


class ConsoleApprover(Approver):
    """Today's terminal prompts and input() behaviour, unchanged in wording."""

    def ask_yes_no(self, action: str, description: str, banner: str) -> bool:
        if banner:
            print(banner, end="" if banner.endswith("\n") else "\n")
        answer = input("Allow? [yes/no]: ").strip().lower()
        return answer == "yes"

    def ask_typed(self, action: str, description: str, banner: str) -> str:
        if banner:
            print(banner, end="" if banner.endswith("\n") else "\n")
        return input(f"Type {action} to approve, anything else denies: ").strip()

    def ask_app_read(self, exe: str, title: str, extra: str) -> AppReadAnswer:
        if extra:
            print(extra, end="" if extra.endswith("\n") else "\n")
        answer = input(
            "Type 'session' (until you exit), 'always' (saved to your trusted "
            "apps), or anything else to refuse: "
        ).strip().lower()
        if answer in ("session", "always"):
            return answer  # type: ignore[return-value]
        return "refuse"

    def ask_continue(self, message: str) -> bool:
        print("\n[PERMISSION REQUIRED - CONFIRM]")
        print("Action: desktop_task_continue")
        print(message)
        answer = input("Allow? [yes/no]: ").strip().lower()
        return answer == "yes"


_approver: Approver = ConsoleApprover()


def get_approver() -> Approver:
    return _approver


def set_approver(approver: Approver) -> Approver:
    """Install approver; return the previous one."""
    global _approver
    previous = _approver
    _approver = approver
    return previous
