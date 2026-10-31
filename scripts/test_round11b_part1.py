"""Round 11B Part 1 — evals must not create files on the real Desktop."""

from __future__ import annotations

import os
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


def _desktop_names(desktop: Path) -> set[str]:
    try:
        return {p.name for p in desktop.iterdir()}
    except OSError as exc:
        print(f"[warn] cannot list Desktop: {type(exc).__name__}")
        return set()


def test_override_maps_away_from_real() -> None:
    from config.paths import (
        USER_FOLDER_NAMES,
        eval_user_folders_active,
        install_eval_user_folders,
        real_user_folders,
        resolve_user_folders,
        set_eval_user_folders,
    )

    real = real_user_folders()
    with tempfile.TemporaryDirectory(prefix="miniai_r11b_uf_") as td:
        mapped = install_eval_user_folders(Path(td))
        _check("override_active", eval_user_folders_active() is True)
        got = resolve_user_folders()
        for name in USER_FOLDER_NAMES:
            _check(
                f"mapped_{name}",
                got[name] == mapped[name] and got[name] != real[name],
                f"got={got[name]} real={real[name]}",
            )
        # expand Desktop\\x → temp
        from config.paths import expand_user_path

        expanded = expand_user_path("Desktop\\probe_r11b.txt")
        _check(
            "expand_uses_temp_desktop",
            str(mapped["Desktop"]) in str(expanded),
            str(expanded),
        )
        set_eval_user_folders(None)
    _check("override_cleared", eval_user_folders_active() is False)
    after = resolve_user_folders(use_cache=False)
    _check(
        "real_restored",
        after["Desktop"] == real["Desktop"],
        f"{after['Desktop']} vs {real['Desktop']}",
    )


def test_code_small_leaves_real_desktop() -> None:
    """Live: run qa_m_code_small once; real Desktop name set must not grow."""
    from config.paths import real_user_folders

    desktop = real_user_folders()["Desktop"]
    before = _desktop_names(desktop)
    print(f"[desktop] path={desktop} n_before={len(before)}")

    # Force planner off; use production model.
    os.environ["MINIAI_PLANNER"] = "off"
    os.environ["MINIAI_EARLY_ABORT"] = "off"
    from eval.run import main as eval_main

    rc = eval_main(
        ["--suite", "full", "--task", "qa_m_code_small", "--repeat", "1", "--force"]
    )
    after = _desktop_names(desktop)
    added = sorted(after - before)
    print(f"[desktop] n_after={len(after)} added={added} eval_rc={rc}")
    _check(
        "no_new_desktop_names",
        added == [],
        f"added={added}",
    )


def main() -> None:
    test_override_maps_away_from_real()
    # Live check only when Lemonade is up (Part 1 requires the live proof).
    try:
        from scripts.check_model_state import check_model_state

        st = check_model_state(write_log=False)
        if st.get("verdict") != "OK":
            print(f"SKIP live desktop check: model {st.get('verdict')}")
        else:
            test_code_small_leaves_real_desktop()
    except Exception as exc:
        _check("live_desktop_check", False, type(exc).__name__)

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
