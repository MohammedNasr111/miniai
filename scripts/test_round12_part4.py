"""Round 12 Part 4 — drag-and-drop attachments (offline)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def test_ui_hooks() -> None:
    html = (PROJECT_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    _check("html_attach_row", 'id="attach-row"' in html)
    _check("html_attach_note", "can't see images yet" in html or "can\u2019t see images yet" in html or "MiniAI can't see images yet" in html)
    _check("js_drop", "onDrop" in js and "addAttachmentsFromFiles" in js)
    _check("js_attached_prefix", "Attached files:" in js)
    _check("js_isImageAttachment", "function isImageAttachment" in js)
    _check("css_attach_chip", ".attach-chip" in css)


def test_dropped_path_same_gate_as_typed() -> None:
    """A dropped path uses the same outside-file wrap as a typed path."""
    from tools.filesystem.untrusted_file import (
        BEGIN_FILE_MARKER,
        is_trusted_local_path,
        maybe_wrap_outside_file,
    )

    with tempfile.TemporaryDirectory() as td:
        outside = Path(td) / "dropped_notes.txt"
        outside.write_text("hello from drop", encoding="utf-8")
        typed = str(outside)
        dropped = str(outside)  # WebView2 drop yields the same absolute path

        _check("outside_not_trusted", not is_trusted_local_path(typed))
        wrapped_typed = maybe_wrap_outside_file(typed, "hello from drop")
        wrapped_dropped = maybe_wrap_outside_file(dropped, "hello from drop")
        _check(
            "same_wrap",
            wrapped_typed == wrapped_dropped and BEGIN_FILE_MARKER in wrapped_typed,
            f"typed_len={len(wrapped_typed)} dropped_len={len(wrapped_dropped)}",
        )

        # Trusted workspace path is not wrapped (typed or dropped).
        from tools.code.paths import workspace_dir

        ws = workspace_dir()
        ws.mkdir(parents=True, exist_ok=True)
        inside = ws / "local.txt"
        inside.write_text("trusted", encoding="utf-8")
        w1 = maybe_wrap_outside_file(str(inside), "trusted")
        w2 = maybe_wrap_outside_file(str(inside), "trusted")
        _check("trusted_same_unwrapped", w1 == w2 == "trusted")


def main() -> None:
    test_ui_hooks()
    test_dropped_path_same_gate_as_typed()
    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
