"""Saved chat transcripts (user text + final answers only; no tool results)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from send2trash import send2trash


def chats_dir() -> Path:
    override = os.environ.get("MINIAI_CHATS_DIR")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local"
        )
        path = Path(base) / "MiniAI" / "chats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def title_from_text(text: str, limit: int = 40) -> str:
    t = " ".join((text or "").strip().split())
    if not t:
        return "New chat"
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def new_chat_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


def chat_path(chat_id: str) -> Path:
    safe = "".join(c for c in chat_id if c.isalnum() or c in "-_")
    return chats_dir() / f"{safe}.json"


def load_chat(chat_id: str) -> Optional[dict[str, Any]]:
    path = chat_path(chat_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_chat(doc: dict[str, Any]) -> Path:
    path = chat_path(str(doc["id"]))
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def create_chat(first_user_text: str = "") -> dict[str, Any]:
    now = _now_iso()
    doc = {
        "id": new_chat_id(),
        "created": now,
        "updated": now,
        "title": title_from_text(first_user_text) if first_user_text else "New chat",
        "messages": [],
    }
    return doc


def append_message(
    doc: dict[str, Any],
    role: str,
    text: str,
    sources: Optional[list[dict[str, str]]] = None,
) -> None:
    entry: dict[str, Any] = {
        "role": role,
        "text": text,
        "ts": _now_iso(),
    }
    if sources:
        entry["sources"] = sources
    doc["messages"].append(entry)
    doc["updated"] = entry["ts"]
    if role == "user" and (doc.get("title") in (None, "", "New chat")):
        doc["title"] = title_from_text(text)
    save_chat(doc)


def delete_chat(chat_id: str) -> bool:
    path = chat_path(chat_id)
    if not path.is_file():
        return False
    send2trash(str(path.resolve()))
    return True


def _day_bucket(iso_ts: str, now: datetime) -> str:
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
    except ValueError:
        return "Earlier"
    local_now = now.astimezone() if now.tzinfo else now
    local_dt = dt.astimezone(local_now.tzinfo)
    d0 = local_now.date()
    d1 = local_dt.date()
    delta = (d0 - d1).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    return "Earlier"


def list_chats_grouped() -> list[dict[str, Any]]:
    """Return [{section, items:[{id,title,updated}]}] for Today/Yesterday/Earlier."""
    now = datetime.now().astimezone()
    items: list[dict[str, Any]] = []
    for path in chats_dir().glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "id": doc.get("id") or path.stem,
                "title": doc.get("title") or "Chat",
                "updated": doc.get("updated") or doc.get("created") or "",
            }
        )
    items.sort(key=lambda x: x.get("updated") or "", reverse=True)
    sections: dict[str, list[dict[str, Any]]] = {
        "Today": [],
        "Yesterday": [],
        "Earlier": [],
    }
    for it in items:
        sections[_day_bucket(it["updated"], now)].append(it)
    out = []
    for name in ("Today", "Yesterday", "Earlier"):
        if sections[name]:
            out.append({"section": name, "items": sections[name]})
    return out
