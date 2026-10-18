"""Unit checks for the startup low-memory warning."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts.agent_loop import warn_if_low_memory

FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        msg = warn_if_low_memory(free_gb=3.2)
    out = buf.getvalue()
    from config.settings import MODEL_NEEDED_RAM_GB

    ok_low = (
        msg is not None
        and "Low memory: 3.2 GB free" in msg
        and f"MiniAI needs about {MODEL_NEEDED_RAM_GB} GB" in msg
        and "Close some apps" in msg
        and out.strip() == msg
    )
    report("1-low", ok_low, f"msg={msg!r} out={out!r}")

    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        msg2 = warn_if_low_memory(free_gb=4.0)
    ok_ok = msg2 is None and buf2.getvalue() == ""
    report("2-at-threshold", ok_ok, f"msg={msg2!r}")

    buf3 = io.StringIO()
    with redirect_stdout(buf3):
        msg3 = warn_if_low_memory(free_gb=8.5)
    ok_high = msg3 is None and buf3.getvalue() == ""
    report("3-plenty", ok_high, f"msg={msg3!r}")

    # Patched free_ram_gb path
    with patch("scripts.agent_loop.free_ram_gb", return_value=1.5):
        buf4 = io.StringIO()
        with redirect_stdout(buf4):
            msg4 = warn_if_low_memory()
    ok_patch = msg4 is not None and "1.5 GB free" in msg4
    report("4-patched", ok_patch, f"msg={msg4!r}")

    print(f"FAILURES {len(FAILURES)} {FAILURES}")
    raise SystemExit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
