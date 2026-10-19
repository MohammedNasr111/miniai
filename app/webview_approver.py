"""Approver that renders design-system approval cards in the app window."""

from __future__ import annotations

import json
import threading
from typing import Any, Optional

from security.approver import Approver, AppReadAnswer


class WebviewApprover(Approver):
    """Block the agent thread until the UI calls ``approval_reply``."""

    def __init__(self, bridge: "AppBridge") -> None:
        self._bridge = bridge
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._answer: Optional[str] = None
        self._pending: Optional[dict[str, Any]] = None

    def _ask(self, payload: dict[str, Any]) -> str:
        # Do not hold _lock across wait — resolve/poll_approval need it.
        with self._lock:
            self._answer = None
            self._event.clear()
            self._pending = dict(payload)
        self._bridge.show_approval(payload)
        self._event.wait(timeout=3600)
        with self._lock:
            self._pending = None
            return self._answer if self._answer is not None else ""

    def take_pending(self) -> Optional[dict[str, Any]]:
        """JS poll: return pending approval payload (GUI-thread safe)."""
        with self._lock:
            p = self._pending
            return dict(p) if p is not None else None

    def resolve(self, value: str) -> None:
        with self._lock:
            self._answer = value
            self._pending = None
            self._event.set()

    def ask_yes_no(self, action: str, description: str, banner: str) -> bool:
        if banner:
            print(banner, end="" if banner.endswith("\n") else "\n")
        ans = self._ask(
            {
                "typed": False,
                "action": action,
                "description": description,
                "banner": banner,
                "title": action.replace("_", " ").title(),
            }
        )
        return ans.strip().lower() == "yes"

    def ask_typed(self, action: str, description: str, banner: str) -> str:
        if banner:
            print(banner, end="" if banner.endswith("\n") else "\n")
        return self._ask(
            {
                "typed": True,
                "action": action,
                "description": description,
                "banner": banner,
                "title": action.replace("_", " ").title(),
            }
        )

    def ask_app_read(self, exe: str, title: str, extra: str) -> AppReadAnswer:
        if extra:
            print(extra, end="" if extra.endswith("\n") else "\n")
        ans = self._ask(
            {
                "typed": True,
                "mode": "app_read",
                "action": "session",
                "description": (
                    f"Allow MiniAI to READ the window of {exe} ({title})?\n"
                    "Type session (this chat) or always (save trust)."
                ),
                "banner": extra,
                "title": "Read desktop app",
            }
        )
        if ans in ("session", "always"):
            return ans  # type: ignore[return-value]
        return "refuse"

    def ask_continue(self, message: str) -> bool:
        print("\n[PERMISSION REQUIRED - CONFIRM]")
        print("Action: desktop_task_continue")
        print(message)
        ans = self._ask(
            {
                "typed": False,
                "action": "desktop_task_continue",
                "description": message,
                "banner": "",
                "title": "Continue task",
            }
        )
        return ans.strip().lower() == "yes"


class AppBridge:
    """Application state + WebviewApprover (not passed as js_api directly)."""

    def __init__(self) -> None:
        self.window = None
        self.approver = WebviewApprover(self)
        self._session = None
        self._provider = None
        self.js_api = _JsApi(self)

    def _eval(self, js: str) -> None:
        if self.window is None:
            return
        try:
            self.window.evaluate_js(js)
        except Exception:
            pass

    def _call_js(self, fn: str, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self._eval(f"window.miniai && window.miniai.{fn}({data})")

    def show_approval(self, payload: dict[str, Any]) -> None:
        # Best-effort push; JS also polls poll_approval() for reliability
        # when evaluate_js cannot run from the agent thread.
        self._call_js("on_approval", payload)

    def push_status(self) -> None:
        from config import settings
        from security.gate import is_tainted
        from tools.code.runner import firewall_rule_status

        try:
            fw = firewall_rule_status()
        except Exception:
            fw = "unknown"
        runner = (
            "Isolated runner · offline"
            if fw == "INSTALLED"
            else f"Isolated runner · {fw}"
        )
        mem_pct = 0
        mem_label = "—"
        try:
            import psutil

            vm = psutil.virtual_memory()
            used = (vm.total - vm.available) / (1024**3)
            total = vm.total / (1024**3)
            mem_pct = int(round(100 * used / total)) if total else 0
            mem_label = f"{used:.1f} / {total:.1f} GB"
        except Exception:
            pass
        self._call_js(
            "on_status",
            {
                "model": f"{settings.LEMONADE_MODEL} · ready",
                "runner": runner,
                "tainted": is_tainted(),
                "memory_pct": mem_pct,
                "memory_label": mem_label,
            },
        )

    def send_message(self, text: str) -> None:
        t = threading.Thread(target=self._run_turn, args=(text,), daemon=True)
        t.start()

    def _run_turn(self, text: str) -> None:
        try:
            from llm.lemonade.provider import LemonadeProvider
            from scripts.agent_loop import _require_lemonade
            from scripts.chat import new_session, run_user_turn
            from security.approver import set_approver
            from security.gate import is_tainted, reset_session

            if self._session is None:
                _require_lemonade()
                reset_session()
                set_approver(self.approver)
                self._provider = LemonadeProvider()
                self._session = new_session(self._provider)

            answer = run_user_turn(self._session, text)
            steps: list[dict[str, str]] = []
            if self._session.transcript is not None:
                path = self._session.transcript.path
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        ev = json.loads(line)
                        if ev.get("type") == "tool_call":
                            steps.append(
                                {"name": str(ev.get("name") or "tool"), "t": ""}
                            )
                except Exception:
                    pass
            if steps:
                self._call_js("on_tools", steps)
            self._call_js(
                "on_answer",
                {"text": answer or "", "sources": [], "tainted": is_tainted()},
            )
            self.push_status()
        except Exception as exc:
            self._call_js("on_error", f"{type(exc).__name__}: {exc}")


class _JsApi:
    """Thin surface exposed to JS — no Window / bridge cycles for pywebview."""

    def __init__(self, bridge: AppBridge) -> None:
        self._bridge = bridge

    def ready(self) -> None:
        self._bridge.push_status()

    def poll_approval(self) -> Optional[dict[str, Any]]:
        return self._bridge.approver.take_pending()

    def approval_reply(self, value: str) -> None:
        self._bridge.approver.resolve(str(value) if value is not None else "")

    def send_message(self, text: str) -> None:
        self._bridge.send_message(str(text or ""))
