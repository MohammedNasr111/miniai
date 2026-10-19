"""Approver + AppBridge for the pywebview UI (js_api, nonces, chats)."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from app.tool_labels import format_duration, label_for
from security.approver import Approver, AppReadAnswer

logger = logging.getLogger(__name__)

_HTTP_URL = re.compile(r"^https?://", re.I)
CANCEL_NOTE = (
    "Cancelled. Actions you already approved were not undone."
)


class WebviewApprover(Approver):
    """Block the agent thread until the UI calls ``approval_reply``."""

    def __init__(self, bridge: "AppBridge") -> None:
        self._bridge = bridge
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._answer: Optional[str] = None
        self._pending: Optional[dict[str, Any]] = None
        self._nonce: Optional[str] = None

    def _ask(self, payload: dict[str, Any]) -> str:
        nonce = secrets.token_hex(16)
        body = dict(payload)
        body["id"] = nonce
        with self._lock:
            self._answer = None
            self._event.clear()
            self._nonce = nonce
            self._pending = body
        self._bridge.show_approval(body)
        # Wait in slices so Stop can cancel a pending approval.
        while not self._event.wait(timeout=0.25):
            if self._bridge.is_cancelled():
                with self._lock:
                    self._pending = None
                    self._nonce = None
                    self._answer = ""
                raise KeyboardInterrupt()
        with self._lock:
            self._pending = None
            self._nonce = None
            return self._answer if self._answer is not None else ""

    def take_pending(self) -> Optional[dict[str, Any]]:
        with self._lock:
            p = self._pending
            return dict(p) if p is not None else None

    def resolve(self, nonce: str, value: str) -> bool:
        """Accept reply only when nonce matches the single pending id."""
        with self._lock:
            if self._nonce is None or nonce != self._nonce:
                logger.warning(
                    "approval_reply ignored: stale or wrong id (got %r)",
                    (nonce or "")[:32],
                )
                return False
            self._answer = value
            self._pending = None
            self._nonce = None
            self._event.set()
            return True

    def force_deny(self) -> None:
        with self._lock:
            if self._nonce is None:
                return
            self._answer = ""
            self._pending = None
            self._nonce = None
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
        self._cancel = threading.Event()
        self._turn_lock = threading.Lock()
        self._busy = False
        self._chat_doc: Optional[dict[str, Any]] = None
        self._turn_steps: list[dict[str, Any]] = []
        self._turn_t0 = 0.0
        self._status_stop = threading.Event()
        self._external_log: list[str] = []  # for tests

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def _eval(self, js: str) -> None:
        if self.window is None:
            return
        try:
            self.window.evaluate_js(js)
        except Exception:
            pass

    def _call_js(self, fn: str, payload: Any = None) -> None:
        if payload is None:
            self._eval(f"window.miniai && window.miniai.{fn}()")
        else:
            data = json.dumps(payload, ensure_ascii=False)
            self._eval(f"window.miniai && window.miniai.{fn}({data})")

    def show_approval(self, payload: dict[str, Any]) -> None:
        self._call_js("on_approval", payload)

    def start_status_loop(self) -> None:
        def _loop() -> None:
            while not self._status_stop.wait(10.0):
                self.push_status()

        threading.Thread(target=_loop, daemon=True).start()
        self.push_status()

    def stop_status_loop(self) -> None:
        self._status_stop.set()

    def _loaded_model_name(self) -> str:
        from config import settings

        configured = settings.LEMONADE_MODEL
        try:
            url = f"{settings.LEMONADE_BASE_URL.rstrip('/')}/health"
            data = requests.get(url, timeout=2).json()
            models = data.get("all_models_loaded") or []
            # Prefer an LLM whose name matches settings; else first LLM.
            llms = [
                m
                for m in models
                if isinstance(m, dict)
                and m.get("type") == "llm"
                and m.get("loaded")
            ]
            for m in llms:
                name = m.get("model_name") or ""
                if name == configured or configured in name or name in configured:
                    return name
            if llms:
                return str(llms[0].get("model_name") or configured)
        except Exception:
            pass
        return configured

    def push_status(self) -> None:
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
        mem_level = "ok"
        try:
            import psutil

            vm = psutil.virtual_memory()
            used = (vm.total - vm.available) / (1024**3)
            total = vm.total / (1024**3)
            mem_pct = int(round(100 * used / total)) if total else 0
            mem_label = f"{used:.1f} / {total:.1f} GB"
            if mem_pct > 92:
                mem_level = "danger"
            elif mem_pct > 80:
                mem_level = "warn"
        except Exception:
            pass
        model = self._loaded_model_name()
        self._call_js(
            "on_status",
            {
                "model": f"{model} · ready",
                "runner": runner,
                "tainted": is_tainted(),
                "memory_pct": mem_pct,
                "memory_label": mem_label,
                "memory_level": mem_level,
            },
        )

    def open_external(self, url: str) -> dict[str, Any]:
        raw = (url or "").strip()
        self._external_log.append(raw)
        if not _HTTP_URL.match(raw):
            logger.warning("open_external refused: %r", raw[:120])
            return {"ok": False, "error": "refused"}
        try:
            parsed = urlparse(raw)
            if parsed.scheme.lower() not in ("http", "https"):
                logger.warning("open_external refused scheme: %r", parsed.scheme)
                return {"ok": False, "error": "refused"}
            os.startfile(raw)  # noqa: S606 — intentional user browser open
            return {"ok": True}
        except Exception as exc:
            logger.warning("open_external failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def send_message(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._turn_lock:
            if self._busy:
                return
            self._busy = True
            self._cancel.clear()
        threading.Thread(target=self._run_turn, args=(text,), daemon=True).start()

    def stop_turn(self) -> None:
        self._cancel.set()
        self.approver.force_deny()

    def new_chat(self) -> dict[str, Any]:
        from scripts.chat import end_session, new_session
        from security.gate import reset_session

        self.stop_turn()
        if self._session is not None:
            try:
                end_session(self._session)
            except Exception:
                pass
        reset_session()
        if self._provider is not None:
            self._session = new_session(self._provider)
        else:
            self._session = None
        self._chat_doc = None
        self._busy = False
        self._cancel.clear()
        return {"ok": True, "history": self.list_chats()}

    def list_chats(self) -> list[dict[str, Any]]:
        from app.chats import list_chats_grouped

        return list_chats_grouped()

    def open_chat(self, chat_id: str) -> dict[str, Any]:
        from app.chats import load_chat

        doc = load_chat(chat_id)
        if doc is None:
            return {"ok": False, "error": "not found"}
        # Read-only view — do not restore taint / browser / session.
        return {
            "ok": True,
            "readonly": True,
            "chat": doc,
            "note": "Continue in a new chat",
        }

    def delete_chat(self, chat_id: str) -> dict[str, Any]:
        from app.chats import delete_chat

        ok = delete_chat(chat_id)
        return {"ok": ok, "history": self.list_chats()}

    def _ensure_session(self) -> None:
        from llm.lemonade.provider import LemonadeProvider
        from scripts.agent_loop import _require_lemonade
        from scripts.chat import new_session
        from security.approver import set_approver
        from security.gate import reset_session

        if self._session is None:
            _require_lemonade()
            reset_session()
            set_approver(self.approver)
            self._provider = LemonadeProvider()
            self._session = new_session(self._provider)

    def _on_tool_start(self, name: str, _args: Any) -> None:
        step = {
            "tool": name,
            "name": label_for(name, done=False) + "…",
            "t": "",
            "running": True,
        }
        self._turn_steps.append(step)
        self._push_live_activity(waiting=False)

    def _on_tool_end(self, name: str, elapsed: float, _outcome: str) -> None:
        for step in reversed(self._turn_steps):
            if step.get("tool") == name and step.get("running"):
                step["running"] = False
                step["name"] = label_for(name, done=True)
                step["t"] = format_duration(elapsed)
                break
        self._push_live_activity(waiting=False)

    def _push_live_activity(self, waiting: bool) -> None:
        total = time.perf_counter() - self._turn_t0 if self._turn_t0 else 0.0
        steps = [
            {
                "name": s["name"],
                "t": s.get("t") or "",
                "running": bool(s.get("running")),
            }
            for s in self._turn_steps
        ]
        self._call_js(
            "on_activity",
            {
                "steps": steps,
                "waiting": waiting,
                "total": format_duration(total),
                "running": any(s.get("running") for s in self._turn_steps),
            },
        )

    def _run_turn(self, text: str) -> None:
        from app.chats import append_message, create_chat
        from scripts.chat import run_user_turn
        from security.approver import set_approver
        from security.gate import is_tainted

        try:
            self._ensure_session()
            set_approver(self.approver)
            if self._chat_doc is None:
                self._chat_doc = create_chat(text)
            append_message(self._chat_doc, "user", text)
            self._turn_steps = []
            self._turn_t0 = time.perf_counter()
            self._call_js(
                "on_activity",
                {"steps": [], "waiting": False, "total": "0s", "running": True},
            )

            answer = run_user_turn(
                self._session,
                text,
                on_tool_start=self._on_tool_start,
                on_tool_end=self._on_tool_end,
                cancel_check=self.is_cancelled,
            )
            total = format_duration(time.perf_counter() - self._turn_t0)
            steps = [
                {
                    "name": s["name"]
                    if not s.get("running")
                    else label_for(s["tool"], done=True),
                    "t": s.get("t") or "",
                    "running": False,
                }
                for s in self._turn_steps
            ]
            sources = _extract_sources(answer or "")
            append_message(self._chat_doc, "assistant", answer or "", sources)
            self._call_js(
                "on_answer",
                {
                    "text": answer or "",
                    "sources": sources,
                    "tainted": is_tainted(),
                    "steps": steps,
                    "total": total,
                },
            )
            self._call_js("on_history", self.list_chats())
            self.push_status()
        except KeyboardInterrupt:
            self._call_js("on_cancelled", {"note": CANCEL_NOTE})
            self.push_status()
        except Exception as exc:
            self._call_js("on_error", f"{type(exc).__name__}: {exc}")
        finally:
            with self._turn_lock:
                self._busy = False
                self._cancel.clear()


def _extract_sources(text: str) -> list[dict[str, str]]:
    urls = re.findall(r"https?://[^\s\)\]\>\"']+", text or "")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for u in urls:
        u = u.rstrip(".,;:")
        if u in seen:
            continue
        seen.add(u)
        host = urlparse(u).netloc or u
        out.append({"label": host, "url": u})
        if len(out) >= 8:
            break
    return out


class _JsApi:
    """Thin surface exposed to JS — no Window / bridge cycles for pywebview."""

    def __init__(self, bridge: AppBridge) -> None:
        self._bridge = bridge

    def ready(self) -> None:
        self._bridge.push_status()
        self._bridge._call_js("on_history", self._bridge.list_chats())

    def poll_approval(self) -> Optional[dict[str, Any]]:
        return self._bridge.approver.take_pending()

    def approval_reply(self, nonce: str, value: str = "") -> bool:
        return self._bridge.approver.resolve(
            str(nonce) if nonce is not None else "",
            str(value) if value is not None else "",
        )

    def send_message(self, text: str) -> None:
        self._bridge.send_message(str(text or ""))

    def stop_turn(self) -> None:
        self._bridge.stop_turn()

    def new_chat(self) -> dict[str, Any]:
        return self._bridge.new_chat()

    def list_chats(self) -> list[dict[str, Any]]:
        return self._bridge.list_chats()

    def open_chat(self, chat_id: str) -> dict[str, Any]:
        return self._bridge.open_chat(str(chat_id or ""))

    def delete_chat(self, chat_id: str) -> dict[str, Any]:
        return self._bridge.delete_chat(str(chat_id or ""))

    def open_external(self, url: str) -> dict[str, Any]:
        return self._bridge.open_external(str(url or ""))
