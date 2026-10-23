"""Offline tests: list_directory sizes/sort/limit and binary-safe read_file."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.filesystem.fs_tools import (  # noqa: E402
    human_size,
    list_directory,
    read_file,
)

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="miniai_fs_list_") as tmp:
        root = Path(tmp)
        (root / "a_small.txt").write_text("hi", encoding="utf-8")
        (root / "b_big.txt").write_bytes(b"x" * 5000)
        (root / "c_mid.txt").write_bytes(b"y" * 2000)
        (root / "subdir").mkdir()
        (root / "pack.zip").write_bytes(b"PK\x03\x04" + b"\x00" * 640)
        (root / "app.exe").write_bytes(b"MZ" + b"\x00" * 100)
        (root / "doc.pdf").write_bytes(b"%PDF-1.4\n" + b"\x00" * 50)
        (root / "sheet.docx").write_bytes(b"PK" + b"\x00" * 40)
        (root / "nulled.bin").write_bytes(b"text\x00more")
        big_text = "A" * 50_000
        (root / "long.txt").write_text(big_text, encoding="utf-8")

        entries = list_directory(str(root), sort_by="size", limit=5)
        _check(
            "list_has_size_fields",
            all(
                "name" in e and "type" in e and "size_bytes" in e and "size" in e
                for e in entries
            ),
            f"n={len(entries)} sample={entries[0] if entries else None}",
        )
        file_entries = [e for e in entries if e["type"] == "file"]
        sizes = [e["size_bytes"] for e in file_entries]
        _check(
            "list_sort_size_desc_default",
            sizes == sorted(sizes, reverse=True),
            f"sizes={sizes}",
        )
        asc = list_directory(str(root), sort_by="size", descending=False, limit=5)
        asc_sizes = [e["size_bytes"] for e in asc if e["type"] == "file"]
        _check(
            "list_sort_size_asc_explicit",
            asc_sizes == sorted(asc_sizes),
            f"sizes={asc_sizes}",
        )
        _check("list_limit_5", len(entries) <= 5, f"len={len(entries)}")

        by_name = list_directory(str(root), sort_by="name", limit=1000)
        names = [e["name"] for e in by_name]
        _check(
            "list_sort_name",
            names == sorted(names, key=str.lower),
            f"names={names}",
        )

        _check("human_640kb", "640" in human_size(640 * 1024), human_size(640 * 1024))
        _check("human_4mb", "4.2" in human_size(int(4.2 * 1024 * 1024)) or "4" in human_size(int(4.2 * 1024 * 1024)), human_size(int(4.2 * 1024 * 1024)))

        z = read_file(str(root / "pack.zip"))
        _check(
            "refuse_zip",
            "binary" in z.lower() and "zip" in z.lower() and "list_directory" in z,
            z[:200],
        )
        e = read_file(str(root / "app.exe"))
        _check("refuse_exe", "binary" in e.lower() and "executable" in e.lower(), e[:200])
        p = read_file(str(root / "doc.pdf"))
        _check("refuse_pdf_knowledge", "knowledge" in p.lower() and "pdf" in p.lower(), p[:200])
        d = read_file(str(root / "sheet.docx"))
        _check("refuse_docx", "not supported" in d.lower(), d[:200])
        n = read_file(str(root / "nulled.bin"))
        _check("refuse_nul_probe", "binary" in n.lower(), n[:200])
        ok_txt = read_file(str(root / "a_small.txt"))
        _check("read_text_ok", ok_txt == "hi", repr(ok_txt))
        long = read_file(str(root / "long.txt"))
        _check(
            "truncate_40k",
            "[truncated:" in long and "40000" in long and len(long) < 50_500,
            f"len={len(long)} head={long[-80:]}",
        )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
