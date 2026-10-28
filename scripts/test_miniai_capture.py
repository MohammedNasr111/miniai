"""Round 8e: MiniAI HWND capture refuses wrong title / failed foreground."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import miniai_capture as mc  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> int:
    # --- title gate ---
    with patch.object(mc, "find_miniai_hwnd", return_value=0):
        out = Path(tempfile.mkdtemp()) / "no_hwnd.png"
        ok = mc.capture_miniai_window(out)
        _check("refuse_no_hwnd", ok is False and not out.is_file(), f"ok={ok} exists={out.is_file()}")

    with patch.object(mc, "find_miniai_hwnd", return_value=42):
        with patch.object(mc, "window_title", return_value="Claude"):
            out = Path(tempfile.mkdtemp()) / "wrong_title.png"
            ok = mc.capture_miniai_window(out, hwnd=42)
            _check(
                "refuse_wrong_title",
                ok is False and not out.is_file(),
                f"ok={ok} exists={out.is_file()}",
            )

    # --- foreground gate ---
    with patch.object(mc, "window_title", return_value="MiniAI"):
        with patch.object(mc.user32, "SetForegroundWindow", return_value=1):
            with patch.object(mc.user32, "GetForegroundWindow", return_value=99):
                ok_fg, err = mc.assert_miniai_foreground(42)
                _check(
                    "refuse_wrong_foreground",
                    ok_fg is False and "foreground" in err,
                    err,
                )

    with patch.object(mc, "window_title", return_value="MiniAI"):
        with patch.object(mc.user32, "SetForegroundWindow", return_value=1):
            with patch.object(mc.user32, "GetForegroundWindow", return_value=42):
                ok_fg, err = mc.assert_miniai_foreground(42)
                _check("accept_matching_foreground", ok_fg is True and err == "", err)

    # --- capture aborts before save when foreground fails mid-flight ---
    with patch.object(mc, "find_miniai_hwnd", return_value=42):
        with patch.object(mc, "assert_miniai_foreground", return_value=(False, "foreground=1 want=42")):
            out = Path(tempfile.mkdtemp()) / "no_save.png"
            ok = mc.capture_miniai_window(out, hwnd=42)
            _check(
                "no_file_on_foreground_fail",
                ok is False and not out.is_file(),
                f"ok={ok} exists={out.is_file()}",
            )

    # --- successful path writes only after gates pass (PrintWindow mocked) ---
    from PIL import Image

    fake = Image.new("RGB", (120, 80), (18, 24, 33))

    def _ok_fg(hwnd: int):
        return True, ""

    def _get_rect(h, pref):
        # pref is byref(RECT); contents live on ._obj in some ctypes builds —
        # fill via the original RECT we control instead.
        rect = pref._obj if hasattr(pref, "_obj") else pref
        rect.left = 10
        rect.top = 20
        rect.right = 130
        rect.bottom = 100
        return 1

    with patch.object(mc, "find_miniai_hwnd", return_value=42):
        with patch.object(mc, "assert_miniai_foreground", side_effect=_ok_fg):
            with patch.object(mc, "window_title", return_value="MiniAI"):
                with patch.object(mc.user32, "GetWindowRect", side_effect=_get_rect):
                    with patch.object(mc, "_printwindow_capture", return_value=fake):
                        out = Path(tempfile.mkdtemp()) / "ok.png"
                        ok = mc.capture_miniai_window(out, hwnd=42)
                        _check(
                            "saves_when_gates_pass",
                            ok is True and out.is_file() and out.stat().st_size > 0,
                            f"ok={ok} size={out.stat().st_size if out.is_file() else 0}",
                        )
                        if out.is_file():
                            got = Image.open(out)
                            _check(
                                "saved_is_rgb_miniai_sized",
                                got.size == (120, 80),
                                str(got.size),
                            )

    print()
    print(f"FAILURES={len(FAILURES)} {FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
