"""Offline: redirected LOCALAPPDATA keeps trusted_apps temp; runner stays real."""

from __future__ import annotations

import os
import sys
import tempfile
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


def _any_junction(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            try:
                if os.path.isjunction(p):
                    found.append(p)
            except OSError:
                continue
    return found


def main() -> int:
    from config.paths import real_local_appdata
    from tests.support import use_temp_data

    real = real_local_appdata()
    # Fresh redirect via use_temp_data (no junctions).
    root = use_temp_data()
    from security.app_trust import trusted_apps_path
    from tools.code.paths import runner_python, runner_venv_dir

    trust = trusted_apps_path()
    runner = runner_python()
    venv = runner_venv_dir()

    trust_res = trust.resolve()
    root_res = root.resolve()
    real_trust = (real / "MiniAI" / "trusted_apps.json").resolve()
    _check(
        "trusted_apps_under_temp",
        root_res in trust_res.parents or trust_res == root_res / "LocalAppData" / "MiniAI" / "trusted_apps.json",
        f"trust={trust} root={root}",
    )
    _check(
        "trusted_apps_not_real",
        trust_res != real_trust,
        f"trust={trust_res} real={real_trust}",
    )
    _check(
        "runner_under_real",
        str(venv).startswith(str(real / "MiniAI"))
        and str(runner).startswith(str(real / "MiniAI")),
        f"venv={venv} runner={runner}",
    )
    _check(
        "runner_not_under_temp",
        str(root) not in str(runner),
        f"runner={runner}",
    )
    junctions = _any_junction(root)
    _check("no_junctions_in_temp", junctions == [], f"found={junctions}")

    # Also: env LOCALAPPDATA alone must not move runner.
    tmp = Path(tempfile.mkdtemp(prefix="miniai_pathcheck_"))
    os.environ["LOCALAPPDATA"] = str(tmp)
    from importlib import reload
    import tools.code.paths as code_paths

    reload(code_paths)
    _check(
        "runner_ignores_env_localappdata",
        str(code_paths.runner_venv_dir()).startswith(str(real / "MiniAI")),
        f"venv={code_paths.runner_venv_dir()}",
    )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
