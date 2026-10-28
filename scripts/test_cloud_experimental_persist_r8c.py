"""Round 8c Part 1: Experimental: cloud brain persists in app.json across restart."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from app.prefs import (  # noqa: E402
    get_cloud_experimental,
    load_prefs,
    prefs_path,
    set_cloud_experimental,
)

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    _check("start_off", get_cloud_experimental() is False, repr(get_cloud_experimental()))
    set_cloud_experimental(True)
    _check("set_on", get_cloud_experimental() is True)
    path = prefs_path()
    _check("app_json_exists", path.is_file(), str(path))
    raw = json.loads(path.read_text(encoding="utf-8"))
    _check(
        "app_json_flag",
        raw.get("cloud_experimental") is True,
        repr(raw),
    )
    # Simulate restart: drop in-process state and reload from disk.
    _check("reload_on", load_prefs().get("cloud_experimental") is True)
    _check("get_after_reload", get_cloud_experimental() is True)
    set_cloud_experimental(False)
    _check("set_off", get_cloud_experimental() is False)
    raw2 = json.loads(path.read_text(encoding="utf-8"))
    _check("app_json_off", raw2.get("cloud_experimental") is False, repr(raw2))

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
