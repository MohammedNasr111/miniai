"""Create/update Desktop and Start Menu MiniAI.lnk with icon + AppUserModelID."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_USER_MODEL_ID = "MiniAI.Desktop"


def _write_lnk(lnk: Path, pythonw: Path, ico: Path) -> None:
    from win32com.propsys import propsys, pscon  # type: ignore
    from win32com.shell import shellcon  # type: ignore
    import win32com.client  # type: ignore

    lnk.parent.mkdir(parents=True, exist_ok=True)
    wsh = win32com.client.Dispatch("WScript.Shell")
    sc = wsh.CreateShortcut(str(lnk))
    sc.TargetPath = str(pythonw)
    sc.Arguments = "-m app"
    sc.WorkingDirectory = str(PROJECT_ROOT)
    sc.WindowStyle = 1
    sc.IconLocation = f"{ico},0"
    sc.Description = "MiniAI local assistant"
    sc.Save()

    store = propsys.SHGetPropertyStoreFromParsingName(
        str(lnk), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore
    )
    store.SetValue(
        pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_USER_MODEL_ID)
    )
    store.Commit()
    print(f"Created {lnk}")


def main() -> int:
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.gen_miniai_assets import main as gen

    gen()

    pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not pythonw.is_file():
        print(f"venv python not found: {pythonw}", file=sys.stderr)
        return 1

    ico = PROJECT_ROOT / "app" / "assets" / "miniai.ico"

    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home() / "OneDrive" / "Desktop"
    _write_lnk(desktop / "MiniAI.lnk", pythonw, ico)

    # Per-user Start menu (no elevation).
    appdata = os.environ.get("APPDATA") or str(
        Path.home() / "AppData" / "Roaming"
    )
    start_menu = (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )
    _write_lnk(start_menu / "MiniAI.lnk", pythonw, ico)

    print(f"Target: {pythonw} -m app")
    print(f"icon: {ico}")
    print(f"AppUserModel.ID={APP_USER_MODEL_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())