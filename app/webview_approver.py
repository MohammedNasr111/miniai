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

from app.action_classes import (
    class_for,
    detail_for,
    format_duration,
    label_for,
    ticket_copy,
)
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
                "ticket": ticket_copy(action, description),
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
                "ticket": ticket_copy(action, description),
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
        self._model_ready = threading.Event()
        self._model_loading = False
        self._model_ready.set()  # until warm-up starts; flipped in start_model_warmup
        self._warmup_started = False
        self._last_tok_s: float = 0.0
        self._stream_t0: float = 0.0
        self._stream_chars: int = 0

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
        self.start_model_warmup()

    def stop_status_loop(self) -> None:
        self._status_stop.set()

    def _health_llms(self) -> list[dict[str, Any]]:
        from config import settings

        try:
            url = f"{settings.LEMONADE_BASE_URL.rstrip('/')}/health"
            data = requests.get(url, timeout=2).json()
            models = data.get("all_models_loaded") or []
            return [
                m
                for m in models
                if isinstance(m, dict)
                and m.get("type") == "llm"
                and m.get("loaded")
            ]
        except Exception:
            return []

    def _model_is_loaded(self) -> bool:
        from config import settings

        configured = settings.LEMONADE_MODEL
        for m in self._health_llms():
            name = m.get("model_name") or ""
            if name == configured or configured in name or name in configured:
                return True
        return bool(self._health_llms())

    def _loaded_model_name(self) -> str:
        from config import settings

        configured = settings.LEMONADE_MODEL
        llms = self._health_llms()
        for m in llms:
            name = m.get("model_name") or ""
            if name == configured or configured in name or name in configured:
                return name
        if llms:
            return str(llms[0].get("model_name") or configured)
        return configured

    def start_model_warmup(self) -> None:
        """Background tiny chat so the first user turn is not a cold load."""
        if self._warmup_started:
            return
        self._warmup_started = True
        if self._model_is_loaded():
            self._model_loading = False
            self._model_ready.set()
            self.push_status()
            return

        self._model_loading = True
        self._model_ready.clear()
        self.push_status()

        def _warm() -> None:
            from config import settings
            from llm.base import ChatMessage
            from llm.lemonade.provider import LemonadeProvider

            try:
                provider = LemonadeProvider()
                # Long timeout: cold load of a ~17 GB model.
                provider.chat(
                    [ChatMessage(role="user", content="ping")],
                    timeout=max(600, int(settings.LEMONADE_TIMEOUT_SECONDS)),
                )
            except Exception as exc:
                logger.warning("model warm-up failed: %s", exc)
            finally:
                self._model_loading = False
                self._model_ready.set()
                try:
                    self.push_status()
                except Exception:
                    pass

        threading.Thread(target=_warm, daemon=True).start()

    def push_status(self) -> None:
        from security.gate import is_tainted
        from tools.code.runner import firewall_rule_status

        try:
            fw = firewall_rule_status()
        except Exception:
            fw = "unknown"
        runner = (
            "Isolated runner, offline"
            if fw == "INSTALLED"
            else f"Isolated runner, {fw}"
        )
        mem_pct = 0
        mem_label = "n/a"
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
        except Exception as exc:
            logger.info("memory meter unavailable: %s", exc)
        model = self._loaded_model_name()
        display = model[:-5] if model.endswith("-GGUF") else model
        if self._model_loading and not self._model_ready.is_set():
            model_label = "Loading model…"
            model_state = "loading"
        else:
            # Prefer short rail label: "Qwen3 30B, on this PC"
            short = display.replace("-GGUF", "").replace("-", " ")
            if "Qwen3" in short and "30B" in short:
                model_label = "Qwen3 30B, on this PC"
            else:
                model_label = f"{short}, on this PC"
            model_state = "ready"
        selfcheck_label = "not run yet"
        selfcheck_level = "ok"
        try:
            from config.log_rotation import read_selfcheck_summary

            sc = read_selfcheck_summary()
            selfcheck_label = str(sc.get("label") or "not run yet").strip()
            selfcheck_level = sc.get("level") or "ok"
        except Exception as exc:
            logger.info("selfcheck summary unavailable: %s", exc)
            selfcheck_label = "not run yet"
        # Memory label: "16.5 of 23.6 GB" (no slash middle-dot)
        mem_label = mem_label.replace(" / ", " of ")
        self._call_js(
            "on_status",
            {
                "model": model_label,
                "model_state": model_state,
                "runner": runner,
                "tainted": is_tainted(),
                "memory_pct": mem_pct,
                "memory_label": mem_label,
                "memory_level": mem_level,
                "selfcheck": selfcheck_label,
                "selfcheck_level": selfcheck_level,
                "tok_s": self._last_tok_s,
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
        from security.gate import is_tainted, reset_session
        from tools.browser.browser_tools import close_session

        self.stop_turn()
        if self._session is not None:
            try:
                end_session(self._session)
            except Exception:
                pass
        # Fresh agent session: clear taint so the chip matches is_tainted().
        reset_session()
        close_session()
        if self._provider is not None:
            self._session = new_session(self._provider)
        else:
            self._session = None
        self._chat_doc = None
        self._busy = False
        self._cancel.clear()
        try:
            self.push_status()
        except Exception:
            pass
        return {
            "ok": True,
            "history": self.list_chats(),
            "tainted": is_tainted(),
        }

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

    def run_selfcheck_bg(self) -> dict[str, Any]:
        """Run the quick suite in a background thread; refresh rail when done."""

        def _job() -> None:
            import subprocess
            import sys
            from pathlib import Path

            root = Path(__file__).resolve().parents[1]
            py = root / ".venv" / "Scripts" / "python.exe"
            if not py.is_file():
                py = Path(sys.executable)
            try:
                subprocess.run(
                    [
                        str(py),
                        "-m",
                        "eval.run",
                        "--suite",
                        "quick",
                        "--ability",
                        "safety",
                        "--repeat",
                        "1",
                        "--model",
                        "Qwen3-30B-A3B-GGUF",
                    ],
                    cwd=str(root),
                    env={**os.environ, "PYTHONPATH": str(root)},
                    timeout=1800,
                    capture_output=True,
                    text=True,
                )
            except Exception as exc:
                logger.warning("selfcheck bg failed: %s", exc)
            try:
                self.push_status()
            except Exception:
                pass

        threading.Thread(target=_job, daemon=True).start()
        return {"ok": True, "started": True}

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

    def _on_tool_start(self, name: str, args: Any) -> None:
        args_dict = args if isinstance(args, dict) else {}
        step = {
            "tool": name,
            "name": label_for(name, done=False),
            "detail": detail_for(name, args_dict),
            "k": class_for(name),
            "t": "",
            "running": True,
            "args": args_dict,
        }
        self._turn_steps.append(step)
        self._push_live_activity(waiting=False)

    def _on_tool_end(self, name: str, elapsed: float, outcome: str) -> None:
        from app.action_classes import denied_label_for
        from app.chats import save_chat
        from app.footprint import record_tool, ui_payload

        args_dict: dict[str, Any] = {}
        outcome_l = str(outcome or "").lower()
        denied = outcome_l in ("denied", "deny", "cancelled", "canceled")
        ok = outcome_l not in ("error", "denied", "deny", "fail", "failed", "cancelled", "canceled")
        for step in reversed(self._turn_steps):
            if step.get("tool") == name and step.get("running"):
                step["running"] = False
                if denied:
                    step["name"] = denied_label_for(name)
                    step["k"] = "denied"
                    step["denied"] = True
                else:
                    step["name"] = label_for(name, done=True)
                step["t"] = format_duration(elapsed)
                args_dict = step.get("args") or {}
                break
        if self._chat_doc is not None:
            record_tool(self._chat_doc, name, args_dict, ok=ok)
            try:
                save_chat(self._chat_doc)
            except Exception:
                pass
            try:
                self._call_js(
                    "on_footprint", ui_payload(self._chat_doc.get("footprint") or {})
                )
            except Exception:
                pass
        self._push_live_activity(waiting=False)

    def _push_live_activity(self, waiting: bool) -> None:
        total = time.perf_counter() - self._turn_t0 if self._turn_t0 else 0.0
        steps = [
            {
                "tool": s.get("tool") or "",
                "name": s["name"],
                "detail": s.get("detail") or "",
                "k": s.get("k")
                or (
                    "denied"
                    if s.get("denied")
                    else class_for(str(s.get("tool") or ""))
                ),
                "t": s.get("t") or "",
                "running": bool(s.get("running")),
                "denied": bool(s.get("denied")),
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

    def _push_footprint(self) -> None:
        from app.footprint import ensure_footprint, ui_payload

        if self._chat_doc is None:
            return
        ensure_footprint(self._chat_doc)
        self._call_js("on_footprint", ui_payload(self._chat_doc["footprint"]))

    def _friendly_error(self, exc: BaseException) -> str:
        """Map provider failures to short chat text; log the raw error."""
        import requests as req

        logger.exception("turn failed: %s", exc)
        if isinstance(exc, req.Timeout):
            from scripts.chat import TURN_TIMEOUT_MESSAGE

            return TURN_TIMEOUT_MESSAGE
        if isinstance(exc, req.ConnectionError):
            from scripts.chat import TURN_SERVER_DOWN_MESSAGE

            return TURN_SERVER_DOWN_MESSAGE
        if isinstance(exc, req.HTTPError):
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 400:
                from scripts.chat import TURN_TOO_LARGE_MESSAGE

                return TURN_TOO_LARGE_MESSAGE
            return (
                "The local model returned an error. Nothing from this message "
                "was saved; try again or start a new chat."
            )
        # Never dump URLs / stack traces into the chat bubble.
        name = type(exc).__name__
        if name in ("Timeout", "ReadTimeout", "ConnectTimeout"):
            from scripts.chat import TURN_TIMEOUT_MESSAGE

            return TURN_TIMEOUT_MESSAGE
        return "Something went wrong while talking to the model. Try again."

    def _run_turn(self, text: str) -> None:
        from app.chats import append_message, create_chat
        from scripts.chat import run_user_turn
        from security.approver import set_approver
        from security.gate import is_tainted

        try:
            if not self._model_ready.is_set():
                self._call_js(
                    "on_activity",
                    {
                        "steps": [
                            {
                                "name": "Waiting for model to load…",
                                "t": "",
                                "running": True,
                            }
                        ],
                        "waiting": False,
                        "total": "0s",
                        "running": True,
                    },
                )
                if not self._model_ready.wait(timeout=900):
                    self._call_js(
                        "on_error",
                        "The model did not finish loading. Is Lemonade running?",
                    )
                    return
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
            def _on_checking() -> None:
                self._call_js(
                    "on_activity",
                    {
                        "steps": [
                            {
                                "name": s["name"],
                                "t": s.get("t") or "",
                                "running": False,
                            }
                            for s in self._turn_steps
                        ]
                        + [
                            {
                                "name": "Checking the answer against sources…",
                                "t": "",
                                "running": True,
                            }
                        ],
                        "waiting": False,
                        "total": format_duration(
                            time.perf_counter() - self._turn_t0
                        ),
                        "running": True,
                        "checking": True,
                    },
                )

            def _on_stream_delta(accumulated: str) -> None:
                text_so_far = accumulated or ""
                if self._stream_t0 <= 0:
                    self._stream_t0 = time.perf_counter()
                self._stream_chars = len(text_so_far)
                elapsed = max(0.001, time.perf_counter() - self._stream_t0)
                # Rough tok/s: ~4 chars/token for English.
                self._last_tok_s = (self._stream_chars / 4.0) / elapsed
                self._call_js("on_stream_delta", {"text": text_so_far})

            def _on_stream_clear() -> None:
                self._stream_t0 = 0.0
                self._stream_chars = 0
                self._call_js("on_stream_clear", {})

            self._stream_t0 = 0.0
            self._stream_chars = 0
            answer = run_user_turn(
                self._session,
                text,
                on_tool_start=self._on_tool_start,
                on_tool_end=self._on_tool_end,
                cancel_check=self.is_cancelled,
                on_checking=_on_checking,
                on_stream_delta=_on_stream_delta,
                on_stream_clear=_on_stream_clear,
            )
            total = format_duration(time.perf_counter() - self._turn_t0)
            steps = [
                {
                    "tool": s.get("tool") or "",
                    "name": s["name"]
                    if not s.get("running")
                    else label_for(s["tool"], done=True),
                    "detail": s.get("detail") or "",
                    "k": s.get("k")
                    or (
                        "denied"
                        if s.get("denied")
                        else class_for(str(s.get("tool") or ""))
                    ),
                    "t": s.get("t") or "",
                    "running": False,
                    "denied": bool(s.get("denied")),
                }
                for s in self._turn_steps
            ]
            sources = _extract_sources(answer or "")
            append_message(self._chat_doc, "assistant", answer or "", sources)
            check_meta = getattr(self._session, "last_check", None)
            check_payload = None
            if isinstance(check_meta, dict) and check_meta.get("fixed"):
                from app.footprint import record_verify

                changed = [
                    c.get("claim") or ""
                    for c in (check_meta.get("claims") or [])
                    if c.get("status") == "contradicted"
                ]
                note = check_meta.get("note") or (
                    "Corrected after checking"
                    if check_meta.get("stream_corrected")
                    else "Corrected after checking sources"
                )
                check_payload = {
                    "fixed": True,
                    "note": note,
                    "claims": changed,
                }
                record_verify(
                    self._chat_doc,
                    note,
                    status="correction" if changed else "pass",
                )
            # Context token estimate from session history when available.
            try:
                from app.footprint import set_context_tokens
                from app.chats import save_chat

                hist = getattr(self._session, "history", None) or []
                est = sum(len(str(getattr(m, "content", m) or "")) for m in hist) // 4
                set_context_tokens(self._chat_doc, est)
                save_chat(self._chat_doc)
            except Exception:
                pass
            from app.footprint import ui_payload

            fp_ui = ui_payload((self._chat_doc or {}).get("footprint") or {})
            self._call_js(
                "on_answer",
                {
                    "text": answer or "",
                    "sources": sources,
                    "tainted": is_tainted(),
                    "steps": steps,
                    "total": total,
                    "check": check_payload,
                    "tok_s": self._last_tok_s,
                    "footprint": fp_ui,
                },
            )
            self._call_js("on_history", self.list_chats())
            self.push_status()
        except KeyboardInterrupt:
            partial = ""
            if self._session is not None:
                partial = getattr(self._session, "last_stream_partial", "") or ""
            self._call_js(
                "on_cancelled",
                {"note": CANCEL_NOTE, "partial": partial},
            )
            self.push_status()
        except Exception as exc:
            self._call_js("on_error", self._friendly_error(exc))
            self.push_status()
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

    def _require_index(self) -> bool:
        """Refuse every bridge call unless the window URL is the app index."""
        from pathlib import Path

        from app.nav_lock import is_app_index_url

        index = Path(__file__).resolve().parent / "ui" / "index.html"
        win = self._bridge.window
        if win is None:
            logger.warning("js_api refused: no window")
            return False
        try:
            url = win.get_current_url() or ""
        except Exception as exc:
            logger.warning("js_api refused: get_current_url failed: %s", exc)
            return False
        if not is_app_index_url(url, index):
            logger.warning("js_api refused: foreign URL %r", url)
            return False
        return True

    def ready(self) -> None:
        if not self._require_index():
            return
        self._bridge.push_status()
        self._bridge._call_js("on_history", self._bridge.list_chats())

    def poll_approval(self) -> Optional[dict[str, Any]]:
        if not self._require_index():
            return None
        return self._bridge.approver.take_pending()

    def approval_reply(self, nonce: str, value: str = "") -> bool:
        if not self._require_index():
            return False
        return self._bridge.approver.resolve(
            str(nonce) if nonce is not None else "",
            str(value) if value is not None else "",
        )

    def send_message(self, text: str) -> None:
        if not self._require_index():
            return
        self._bridge.send_message(str(text or ""))

    def stop_turn(self) -> None:
        if not self._require_index():
            return
        self._bridge.stop_turn()

    def new_chat(self) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        return self._bridge.new_chat()

    def list_chats(self) -> list[dict[str, Any]]:
        if not self._require_index():
            return []
        return self._bridge.list_chats()

    def open_chat(self, chat_id: str) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        return self._bridge.open_chat(str(chat_id or ""))

    def delete_chat(self, chat_id: str) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        return self._bridge.delete_chat(str(chat_id or ""))

    def open_external(self, url: str) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        return self._bridge.open_external(str(url or ""))

    def get_footprint(self) -> dict[str, Any]:
        if not self._require_index():
            return {}
        from app.footprint import empty_footprint, ensure_footprint, ui_payload

        doc = self._bridge._chat_doc
        if doc is None:
            return ui_payload(empty_footprint())
        return ui_payload(ensure_footprint(doc))

    def open_logs(self) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        from pathlib import Path

        logs = Path(__file__).resolve().parents[1] / "logs"
        try:
            os.startfile(str(logs))  # noqa: S606
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def run_selfcheck(self) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        return self._bridge.run_selfcheck_bg()

    def copy_text(self, text: str) -> dict[str, Any]:
        if not self._require_index():
            return {"ok": False, "error": "foreign page"}
        try:
            import ctypes

            # Best-effort: use PowerShell Set-Clipboard via subprocess is heavier;
            # prefer pyperclip if present, else skip.
            try:
                import pyperclip  # type: ignore

                pyperclip.copy(str(text or ""))
                return {"ok": True}
            except Exception:
                pass
            _ = ctypes  # silence unused if no pyperclip
            return {"ok": False, "error": "clipboard unavailable"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
