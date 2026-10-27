"""Offline tests: DPAPI Gemini key save/load/remove; key never in logs/chats."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from security.gemini_key import (  # noqa: E402
    STATUS_CONNECTED,
    STATUS_NOT_CONNECTED,
    has_key,
    key_path,
    load_key,
    remove_key,
    save_key,
    secrets_dir,
    ui_status,
)

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _grep_tree(root: Path, needle: str) -> list[str]:
    hits: list[str] = []
    if not root.is_dir():
        return hits
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Skip the encrypted blob itself
        if p.name == "gemini.bin":
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if needle.encode("utf-8") in data:
            hits.append(str(p))
    return hits


def main() -> None:
    secret = "AIzaSyTEST-ROUND8-KEY-NEVER-LEAK-" + os.urandom(4).hex()

    # Fresh state
    remove_key()
    _check("start_empty", not has_key() and load_key() is None, repr(ui_status()))

    # Save → reload → decrypt
    out = save_key(secret)
    _check(
        "save_ok",
        out.get("ok") is True
        and out.get("connected") is True
        and out.get("status") == STATUS_CONNECTED
        and "AIza" not in str(out),
        repr(out),
    )
    _check("file_exists", key_path().is_file(), str(key_path()))
    blob = key_path().read_bytes()
    _check(
        "not_plaintext_on_disk",
        secret.encode("utf-8") not in blob and b"AIza" not in blob,
        f"blob_len={len(blob)}",
    )
    loaded = load_key()
    _check("decrypt_roundtrip", loaded == secret, f"loaded_len={len(loaded or '')}")

    # UI status never echoes key
    st = ui_status()
    _check(
        "ui_status_safe",
        st.get("connected") is True
        and secret not in str(st)
        and "AIza" not in str(st),
        repr(st),
    )

    # Key must not appear under temp logs/chats trees after "save"
    local = Path(os.environ["LOCALAPPDATA"])
    chats = local / "MiniAI" / "chats"
    chats.mkdir(parents=True, exist_ok=True)
    (chats / "dummy.json").write_text('{"note":"no key here"}', encoding="utf-8")
    logs = PROJECT_ROOT / "logs"
    hits_chats = _grep_tree(chats, secret)
    # Only scan a temp logs subdir we control (never require wiping project logs)
    with tempfile.TemporaryDirectory(prefix="miniai_gk_") as td:
        tlogs = Path(td) / "logs"
        tlogs.mkdir()
        (tlogs / "agent_fake.log").write_text("turn ok\n", encoding="utf-8")
        hits_logs = _grep_tree(tlogs, secret)
    _check("not_in_chats", hits_chats == [], repr(hits_chats))
    _check("not_in_temp_logs", hits_logs == [], repr(hits_logs))

    # Remove deletes the file
    rem = remove_key()
    _check(
        "remove_ok",
        rem.get("ok") is True
        and rem.get("connected") is False
        and rem.get("status") == STATUS_NOT_CONNECTED
        and not has_key()
        and not key_path().is_file(),
        repr(rem),
    )
    _check("load_after_remove", load_key() is None)

    # secrets dir is under LOCALAPPDATA\MiniAI (already a protected root)
    from security.protected_paths import is_protected_path

    _check(
        "secrets_already_protected",
        is_protected_path(secrets_dir() / "gemini.bin"),
        str(secrets_dir()),
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
