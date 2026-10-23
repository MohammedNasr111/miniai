"""Create/update the Desktop MiniAI.lnk with icon + AppUserModelID."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(PROJECT_ROOT))
    # Ensure assets exist.
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
    lnk = desktop / "MiniAI.lnk"

    # WScript.Shell for Target/Icon; then IPropertyStore for AppUserModelID.
    from win32com.propsys import propsys, pscon  # type: ignore
    from win32com.shell import shellcon  # type: ignore
    import win32com.client  # type: ignore

    wsh = win32com.client.Dispatch("WScript.Shell")
    sc = wsh.CreateShortcut(str(lnk))
    sc.TargetPath = str(pythonw)
    sc.Arguments = "-m app"
    sc.WorkingDirectory = str(PROJECT_ROOT)
    sc.WindowStyle = 1
    sc.IconLocation = f"{ico},0"
    sc.Description = "MiniAI local assistant"
    sc.Save()

    # System.AppUserModel.ID so the taskbar uses this shortcut's identity/icon.
    store = propsys.SHGetPropertyStoreFromParsingName(
        str(lnk), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore
    )
    store.SetValue(
        pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType("MiniAI.Desktop")
    )
    store.Commit()
    print(f"Created {lnk}")
    print(f"Target: {pythonw} -m app")
    print(f"icon: {ico}")
    print("AppUserModel.ID=MiniAI.Desktop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
