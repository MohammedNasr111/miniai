"""Launch MiniAI via shortcut and capture taskbar / titlebar icon screenshots."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "app" / "design" / "actual_v5_taskbar.png"
OUT_ICON = PROJECT_ROOT / "app" / "design" / "actual_v5_taskbar_icon.png"


def _capture_screen(path: Path) -> bool:
    from PIL import ImageGrab

    img = ImageGrab.grab(all_screens=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    print(f"SAVED={path} size={img.size}")
    return True


def _crop_taskbar_icon(full: Path, out: Path) -> bool:
    from PIL import Image

    img = Image.open(full)
    w, h = img.size
    # Taskbar usually bottom ~48–60 px; MiniAI button near left after Start.
    # Crop a strip of the bottom center-left where new apps often appear.
    strip_h = min(72, h // 12)
    # Take left portion of taskbar (apps pinned / running).
    region = img.crop((0, h - strip_h, min(w, 900), h))
    region.save(out)
    # Also try a tight crop around first non-start icons (~60–200 px from left).
    tight = img.crop((40, h - strip_h, 220, h))
    tight_path = out.with_name(out.stem + "_tight.png")
    tight.save(tight_path)
    print(f"CROP={out} tight={tight_path}")
    return True


def main() -> int:
    desktop = Path.home() / "Desktop"
    lnk = desktop / "MiniAI.lnk"
    if not lnk.is_file():
        lnk = Path.home() / "OneDrive" / "Desktop" / "MiniAI.lnk"
    if not lnk.is_file():
        print("NO_SHORTCUT")
        return 1

    # Launch via shortcut (os.startfile).
    os.startfile(str(lnk))  # noqa: S606
    # Wait for window.
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = 0
    for _ in range(40):
        time.sleep(0.5)
        hwnd = user32.FindWindowW(None, "MiniAI")
        if hwnd:
            break
    if not hwnd:
        print("WINDOW_NOT_FOUND")
        return 1
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.2)
    _capture_screen(OUT)
    _crop_taskbar_icon(OUT, OUT_ICON)

    # Close the app.
    user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    time.sleep(1.0)
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
