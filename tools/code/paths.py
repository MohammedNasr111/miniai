"""Fixed paths for the isolated code runner and its workspace."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


FIREWALL_RULE_NAME = "MiniAI code runner - block internet"

OUTPUT_CAP = 20_000
PROCESS_MEMORY_LIMIT = 2 * 1024 * 1024 * 1024  # 2 GB
DEFAULT_TIMEOUT_S = 60


def localappdata() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is not set.")
    return Path(local)


def userprofile() -> Path:
    home = os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError("USERPROFILE is not set.")
    return Path(home)


def workspace_dir() -> Path:
    """Low-integrity writable workspace under LocalLow."""
    return userprofile() / "AppData" / "LocalLow" / "MiniAI" / "workspace"


def runner_venv_dir() -> Path:
    """Medium-integrity venv; not writable by low-IL code."""
    return localappdata() / "MiniAI" / "runner-venv"


def runner_python() -> Path:
    """Dedicated interpreter copy used for runs and the firewall rule.

    Windows ``Scripts\\python.exe`` is a venv launcher that re-execs the base
    interpreter (a child process). Job Object ACTIVE_PROCESS=1 forbids that, so
    MiniAI keeps a real ``python.exe`` + DLLs under ``runner-bin\\`` inside the
    venv folder (medium integrity) and launches that path.
    """
    return runner_venv_dir() / "runner-bin" / "python.exe"


def runner_scripts_python() -> Path:
    return runner_venv_dir() / "Scripts" / "python.exe"


def runner_pyvenv_cfg() -> Path:
    return runner_venv_dir() / "pyvenv.cfg"


def runner_base_home() -> Path:
    cfg = runner_pyvenv_cfg()
    if not cfg.is_file():
        raise RuntimeError(
            f"Runner venv config not found at {cfg}. "
            "Create it with: python -m venv %LOCALAPPDATA%\\MiniAI\\runner-venv"
        )
    home: str | None = None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("home"):
            _, _, val = line.partition("=")
            home = val.strip().strip('"')
            break
    if not home:
        raise RuntimeError(f"No 'home' entry in {cfg}")
    return Path(home)


def ensure_workspace() -> Path:
    ws = workspace_dir()
    ws.mkdir(parents=True, exist_ok=True)
    tmp = ws / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return ws


def ensure_runner_python() -> Path:
    """Ensure the dedicated runner-bin python.exe exists; return its path."""
    stub = runner_scripts_python()
    if not stub.is_file():
        raise RuntimeError(
            f"Runner venv not found at {stub}. "
            "Create it with: python -m venv %LOCALAPPDATA%\\MiniAI\\runner-venv"
        )
    home = runner_base_home()
    base_py = home / "python.exe"
    if not base_py.is_file():
        raise RuntimeError(f"Base interpreter not found: {base_py}")

    dest_dir = runner_venv_dir() / "runner-bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_py = dest_dir / "python.exe"

    # Copy interpreter + sibling DLLs once (or refresh if missing).
    need_copy = not dest_py.is_file()
    if not need_copy:
        # If base is newer, refresh.
        try:
            need_copy = base_py.stat().st_mtime > dest_py.stat().st_mtime
        except OSError:
            need_copy = True
    if need_copy:
        shutil.copy2(base_py, dest_py)
        for name in os.listdir(home):
            low = name.lower()
            if low.endswith(".dll") or low in ("python.pdb",):
                src = home / name
                if src.is_file():
                    shutil.copy2(src, dest_dir / name)

    if not dest_py.is_file():
        raise RuntimeError(f"Failed to prepare runner binary at {dest_py}")
    return dest_py


def runner_pythonhome() -> Path:
    """Stdlib location for the copied interpreter (base install)."""
    return runner_base_home()
