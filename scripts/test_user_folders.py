"""Offline: known-folder resolution + path expansion (mocked OneDrive Desktop)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name} - {detail}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} - {detail}")


def main() -> int:
    from config.paths import (
        USER_FOLDER_NAMES,
        clear_user_folders_cache,
        expand_user_path,
        resolve_user_folders,
        user_folders_prompt_line,
    )
    from tools.filesystem.fs_tools import resolve_fs_path

    clear_user_folders_cache()

    od_desktop = Path(r"C:\Users\mohdc\OneDrive\Desktop")
    od_docs = Path(r"C:\Users\mohdc\OneDrive\Documents")
    od_dl = Path(r"C:\Users\mohdc\OneDrive\Downloads")
    od_pic = Path(r"C:\Users\mohdc\OneDrive\Pictures")
    od_music = Path(r"C:\Users\mohdc\OneDrive\Music")
    od_vid = Path(r"C:\Users\mohdc\OneDrive\Videos")
    mocked = {
        "Desktop": od_desktop,
        "Documents": od_docs,
        "Downloads": od_dl,
        "Pictures": od_pic,
        "Music": od_music,
        "Videos": od_vid,
    }

    def known_getter(name: str):
        return mocked.get(name)

    folders = resolve_user_folders(
        known_folder_getter=known_getter,
        use_cache=False,
    )
    for name in USER_FOLDER_NAMES:
        _check(
            f"known_{name}",
            folders[name] == mocked[name],
            f"got={folders[name]}",
        )

    # Registry fallback when known-folder API returns None
    def known_none(_name: str):
        return None

    def reg_getter(reg_name: str):
        mapping = {
            "Desktop": str(od_desktop),
            "Personal": str(od_docs),
            "{374DE290-123F-4565-9164-39C4925E467B}": str(od_dl),
            "My Pictures": str(od_pic),
            "My Music": str(od_music),
            "My Video": str(od_vid),
        }
        return Path(mapping[reg_name]) if reg_name in mapping else None

    via_reg = resolve_user_folders(
        known_folder_getter=known_none,
        registry_getter=reg_getter,
        use_cache=False,
    )
    _check("registry_Desktop", via_reg["Desktop"] == od_desktop, str(via_reg["Desktop"]))

    line = user_folders_prompt_line(mocked)
    _check(
        "prompt_line",
        line.startswith("The user's folders:")
        and "Desktop = " + str(od_desktop) in line
        and "Downloads = " + str(od_dl) in line,
        line[:120],
    )

    cases = [
        (r"Desktop\miniai-test.txt", od_desktop / "miniai-test.txt"),
        (r"~/Desktop/miniai-test.txt", od_desktop / "miniai-test.txt"),
        (r"~\Desktop\miniai-test.txt", od_desktop / "miniai-test.txt"),
        (
            r"%USERPROFILE%\Desktop\miniai-test.txt",
            od_desktop / "miniai-test.txt",
        ),
        (
            str(Path.home() / "Desktop" / "miniai-test.txt"),
            od_desktop / "miniai-test.txt",
        ),
        (r"Downloads\setup.exe", od_dl / "setup.exe"),
        (r"Documents\notes.txt", od_docs / "notes.txt"),
    ]
    for raw, expect in cases:
        got = expand_user_path(raw, folders=mocked)
        _check(
            f"expand:{raw}",
            got == expect,
            f"got={got} expect={expect}",
        )

    # resolve_fs_path uses live folders; monkey via expand with mocked through
    # patching resolve_user_folders cache is heavy — unit-test expand above.
    # Spot-check live Desktop is absolute and named.
    live = resolve_user_folders(use_cache=False)
    _check(
        "live_Desktop_absolute",
        live["Desktop"].is_absolute() and live["Desktop"].name.lower() == "desktop"
        or "onedrive" in str(live["Desktop"]).lower(),
        str(live["Desktop"]),
    )
    # Live expand: relative Desktop should land under live Desktop
    live_file = resolve_fs_path(r"Desktop\_miniai_path_probe.txt")
    _check(
        "resolve_fs_Desktop_relative",
        str(live_file).lower().startswith(str(live["Desktop"]).lower()),
        f"{live_file} under {live['Desktop']}",
    )
    # Must NOT silently use bare C:\Users\<user>\Desktop when OneDrive redirects
    bare = Path.home() / "Desktop"
    if live["Desktop"].resolve() != bare.resolve():
        _check(
            "not_bare_home_Desktop",
            live_file.resolve() != (bare / "_miniai_path_probe.txt").resolve(),
            f"live={live_file} bare_would_be={bare / '_miniai_path_probe.txt'}",
        )
    else:
        _check("not_bare_home_Desktop", True, "Desktop not redirected on this machine")

    # System prompt includes folders line
    from scripts.agent_loop import system_prompt

    sp = system_prompt()
    _check(
        "system_prompt_folders",
        "The user's folders:" in sp and "Desktop =" in sp,
        "has folders line",
    )

    print(f"FAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
