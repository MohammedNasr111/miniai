"""Round 8b Part 3: importable slugs + run_tests rootdir/PYTHONPATH."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from tools.code.paths import workspace_dir  # noqa: E402
from tools.code.project_discover import ensure_task_slug_folder, slugify  # noqa: E402
from tools.code.workspace_tools import _project_root_for_tests, run_tests  # noqa: E402
from tools.code.runner import RunResult  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    s = slugify("Build a command-line expense tracker")
    _check("slug_underscores", "_" in s and "-" not in s, s)
    _check("slug_identifier", s.isidentifier() and s[0].isalpha(), s)
    _check(
        "slug_expense",
        "expense" in s and "tracker" in s,
        s,
    )

    # Unique nonsense words so list_project_candidates cannot match a
    # leftover real-workspace folder (e.g. command-line-expense-tracker).
    uniq = f"zorpwidget{int(__import__('time').time()) % 100000}"
    slug = ensure_task_slug_folder(
        f"Please build a {uniq} cli tool with pytest"
    )
    _check(
        "ensure_importable",
        bool(slug)
        and slug is not None
        and slug.isidentifier()
        and "-" not in slug
        and uniq in slug
        and (workspace_dir() / slug).is_dir(),
        repr(slug),
    )

    # Existing hyphen folder must remain usable (not renamed).
    old = workspace_dir() / "legacy-hyphen-project"
    old.mkdir(parents=True, exist_ok=True)
    (old / "keep.txt").write_text("x", encoding="utf-8")
    _check("legacy_hyphen_kept", old.is_dir() and (old / "keep.txt").is_file())

    # run_tests passes --rootdir and cwd=project
    proj = workspace_dir() / "demo_proj"
    tests = proj / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (proj / "demo_proj.py").write_text("X=1\n", encoding="utf-8")
    (tests / "test_demo.py").write_text(
        "import demo_proj\ndef test_ok():\n    assert demo_proj.X == 1\n",
        encoding="utf-8",
    )
    captured: dict = {}

    def _fake_run_argv(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["cwd"] = kwargs.get("cwd")
        captured["extra_pythonpath"] = list(kwargs.get("extra_pythonpath") or [])
        return RunResult(
            exit_code=0,
            wall_time_s=0.01,
            timed_out=False,
            stdout="1 passed in 0.01s\n",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            script_path=str(tests),
            pid=1,
            memory_limited=False,
        )

    with patch("tools.code.workspace_tools.run_argv", side_effect=_fake_run_argv):
        with patch("tools.code.workspace_tools.check_permission", return_value=None):
            with patch("tools.code.workspace_tools.commit_workspace", return_value=None):
                with patch(
                    "tools.code.workspace_tools.firewall_rule_status",
                    return_value="INSTALLED",
                ):
                    out = run_tests("demo_proj/tests")

    _check("run_tests_ok_wrap", "exit_code: 0" in out or "1 passed" in out, out[:200])
    argv = captured.get("argv") or []
    _check(
        "has_rootdir",
        any(str(a).startswith("--rootdir=") and "demo_proj" in str(a) for a in argv),
        repr(argv),
    )
    cwd = captured.get("cwd")
    _check(
        "cwd_is_project",
        cwd is not None and Path(cwd).resolve() == proj.resolve(),
        repr(cwd),
    )
    pyp = captured.get("extra_pythonpath") or []
    _check(
        "project_on_pythonpath",
        any(Path(p).resolve() == proj.resolve() for p in pyp),
        repr(pyp),
    )
    _check(
        "project_root_helper",
        _project_root_for_tests(tests).resolve() == proj.resolve(),
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
