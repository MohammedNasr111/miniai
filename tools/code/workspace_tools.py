"""Workspace file tools, runs, package install, and project copy-in/out."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from security.gate import Tier, check_permission
from security.protected_paths import assert_not_protected
from tools.code.code_tools import (
    BEGIN_MARKER,
    END_MARKER,
    PREAMBLE,
    _wrap_untrusted,
)
from tools.code.paths import (
    DEFAULT_TIMEOUT_S,
    OUTPUT_CAP,
    PROCESS_MEMORY_LIMIT,
    runner_scripts_python,
    runner_venv_dir,
    workspace_dir,
)
from tools.code.runner import (
    LowIntegrityLaunchError,
    firewall_rule_status,
    format_run_result,
    run_argv,
)
from tools.code.workspace_git import commit_workspace
from tools.code.workspace_paths import (
    WorkspacePathError,
    is_reparse_point,
    numbered_text,
    projects_dir,
    resolve_in_workspace,
)

PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SKIP_DIR_NAMES = {"node_modules", ".venv", "__pycache__"}
MAX_IMPORT_BYTES = 50 * 1024 * 1024
MAX_IMPORT_FILES = 2000
ORIGIN_FILENAME = ".miniai_origin.json"


def ws_read(path: str) -> str:
    check_permission(
        action="ws_read",
        tier=Tier.AUTO_ALLOW,
        description=f"Read workspace file: {path}",
    )
    target = resolve_in_workspace(path, must_exist=True)
    if not target.is_file():
        raise WorkspacePathError(f"Not a file: {path}")
    return target.read_text(encoding="utf-8", errors="replace")


def ws_list(path: str = ".") -> list[str]:
    check_permission(
        action="ws_list",
        tier=Tier.AUTO_ALLOW,
        description=f"List workspace directory: {path}",
    )
    target = resolve_in_workspace(path, must_exist=True)
    if not target.is_dir():
        raise WorkspacePathError(f"Not a directory: {path}")
    return sorted(os.listdir(target))


def _py_syntax_note(path: str, source: str) -> str:
    """If path looks like Python, compile and return a warning on SyntaxError."""
    if not str(path).lower().endswith(".py"):
        return ""
    try:
        compile(source, path, "exec")
    except SyntaxError as exc:
        return (
            f" WARNING: SyntaxError in {path} at line {exc.lineno}: {exc.msg}. "
            "Fix the syntax before run_tests."
        )
    return ""


def ws_write(path: str, content: str) -> str:
    # Gate AUTO_ALLOW (no prompt); TOOL_TIERS marks CONFIRM for the guard.
    check_permission(
        action="ws_write",
        tier=Tier.AUTO_ALLOW,
        description=f"Write workspace file: {path}",
    )
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    target = resolve_in_workspace(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    sha = commit_workspace(f"ws_write {path}")
    return (
        f"Wrote {path} ({len(content.encode('utf-8'))} bytes)."
        + (f" Commit {sha}." if sha else "")
        + _py_syntax_note(path, content)
    )


def ws_edit(path: str, old: str, new: str) -> str:
    check_permission(
        action="ws_edit",
        tier=Tier.AUTO_ALLOW,
        description=f"Edit workspace file: {path}",
    )
    if not isinstance(old, str) or not isinstance(new, str):
        raise TypeError("old and new must be strings")
    if old == "":
        return "Error: old text must not be empty (0 matches would be ambiguous)."
    target = resolve_in_workspace(path, must_exist=True)
    if not target.is_file():
        raise WorkspacePathError(f"Not a file: {path}")
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        return (
            f"Error: old text occurs {count} time(s) in {path}; "
            "ws_edit requires exactly one match."
        )
    updated = text.replace(old, new, 1)
    target.write_text(updated, encoding="utf-8")
    sha = commit_workspace(f"ws_edit {path}")
    return (
        f"Edited {path} (1 replacement)."
        + (f" Commit {sha}." if sha else "")
        + _py_syntax_note(path, updated)
    )


def run_file(path: str, args: Optional[list[str]] = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    args = list(args or [])
    target = resolve_in_workspace(path, must_exist=True)
    if target.suffix.lower() != ".py" or not target.is_file():
        raise WorkspacePathError(f"run_file requires a .py file in the workspace: {path}")
    code = target.read_text(encoding="utf-8", errors="replace")
    fw = firewall_rule_status(force=True)
    mem_gb = PROCESS_MEMORY_LIMIT // (1024**3)
    description = (
        f"Run workspace file: {path}\n"
        f"Args: {args!r}\n"
        f"Limits: wall timeout {timeout_s}s; process memory {mem_gb} GB; "
        f"no child processes; stdout/stderr each capped at {OUTPUT_CAP} characters.\n"
        "Runs isolated: cannot change your files outside its workspace, cannot\n"
        "start other programs, no internet (if the MiniAI firewall rule is\n"
        f"installed - status: {fw}).\n"
        "--- file ---\n"
        f"{numbered_text(code)}\n"
        "--- end file ---"
    )
    check_permission(action="run_file", tier=Tier.CONFIRM, description=description)
    try:
        result = run_argv(
            [str(target), *[str(a) for a in args]],
            timeout_s=float(timeout_s),
            script_path=str(target),
            cwd=workspace_dir(),
        )
    except LowIntegrityLaunchError as exc:
        return (
            "REFUSED: could not launch the code runner at low integrity "
            f"({exc}). Nothing was executed."
        )
    commit_workspace(f"run_file {path}")
    return _wrap_untrusted(format_run_result(result))


def _list_test_files(root: Path) -> list[Path]:
    found: list[Path] = []
    if root.is_file() and root.name.startswith("test_") and root.suffix == ".py":
        return [root]
    if not root.is_dir():
        return []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES and d != ".git"]
        for name in filenames:
            if name.startswith("test_") and name.endswith(".py"):
                found.append(Path(dirpath) / name)
            elif name.endswith("_test.py"):
                found.append(Path(dirpath) / name)
    return sorted(found)


def _pytest_import_roots(target: Path) -> list[str]:
    """Project dirs to put on PYTHONPATH so `from wordcount import` works."""
    roots: list[str] = []
    ws = workspace_dir()
    # eval_wordcount/tests → include eval_wordcount
    if target.is_dir() and target.name in {"tests", "test"}:
        roots.append(str(target.parent))
    elif target.is_file():
        # .../tests/test_foo.py → include project root
        if target.parent.name in {"tests", "test"}:
            roots.append(str(target.parent.parent))
        else:
            roots.append(str(target.parent))
    else:
        roots.append(str(target))
    # Always allow workspace-root imports too
    roots.append(str(ws))
    # de-dupe preserve order
    out: list[str] = []
    for r in roots:
        if r and r not in out:
            out.append(r)
    return out


def run_tests(path: str = "tests", timeout_s: float = DEFAULT_TIMEOUT_S) -> str:
    target = resolve_in_workspace(path, must_exist=True)
    tests = _list_test_files(target)
    fw = firewall_rule_status(force=True)
    mem_gb = PROCESS_MEMORY_LIMIT // (1024**3)
    listing = "\n".join(f"  - {p.relative_to(workspace_dir())}" for p in tests) or "  (none found)"
    description = (
        f"Run pytest in the isolated runner on: {path}\n"
        f"Test files:\n{listing}\n"
        f"Limits: wall timeout {timeout_s}s; process memory {mem_gb} GB; "
        f"no child processes; firewall status: {fw}.\n"
        "Requires pytest installed in the runner venv."
    )
    check_permission(action="run_tests", tier=Tier.CONFIRM, description=description)
    try:
        result = run_argv(
            ["-m", "pytest", str(target), "-q", "--tb=short"],
            timeout_s=float(timeout_s),
            script_path=str(target),
            cwd=workspace_dir(),
            extra_pythonpath=_pytest_import_roots(target),
        )
    except LowIntegrityLaunchError as exc:
        return (
            "REFUSED: could not launch the code runner at low integrity "
            f"({exc}). Nothing was executed."
        )
    commit_workspace(f"run_tests {path}")
    return _wrap_untrusted(format_run_result(result))


def _pip_install(name: str, version: Optional[str]) -> subprocess.CompletedProcess:
    spec = f"{name}=={version}" if version else name
    venv_py = runner_scripts_python()
    if not venv_py.is_file():
        raise RuntimeError(f"Runner venv python not found: {venv_py}")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "--python",
        str(venv_py),
        "install",
        "--only-binary=:all:",
        spec,
    ]
    from config.proc import hidden_subprocess_kwargs

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        **hidden_subprocess_kwargs(),
    )


def install_package(name: str, version: Optional[str] = None) -> str:
    if not isinstance(name, str) or not PACKAGE_NAME_RE.match(name):
        raise ValueError(
            f"Invalid package name {name!r}. Must match "
            f"{PACKAGE_NAME_RE.pattern}"
        )
    if version is not None:
        if not isinstance(version, str) or not re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$", version
        ):
            raise ValueError(f"Invalid version string: {version!r}")
    description = (
        f"Install package into the isolated runner venv.\n"
        f"Name: {name}\n"
        f"Version: {version if version is not None else '(latest)'}\n"
        "This installs third-party code from PyPI into the\n"
        "isolated runner. Check the name spelling carefully."
    )
    check_permission(
        action="install_package",
        tier=Tier.CONFIRM,
        description=description,
    )
    cp = _pip_install(name, version)
    out = (cp.stdout or "") + (cp.stderr or "")
    if cp.returncode != 0:
        return (
            f"pip install failed (exit {cp.returncode}).\n"
            f"{out[-8000:]}"
        )
    return f"pip install succeeded for {name}" + (
        f"=={version}" if version else ""
    ) + f".\n{out[-8000:]}"


def _walk_no_reparse(
    root: Path,
) -> tuple[list[Path], list[str], int]:
    """Walk root without following junctions/symlinks.

    Returns (files, skipped_reparse_relpaths, total_bytes).
    """
    files: list[Path] = []
    skipped: list[str] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Drop skipped names and reparse-point directories (do not descend).
        keep_dirs: list[str] = []
        for d in list(dirnames):
            if d in SKIP_DIR_NAMES:
                continue
            child = Path(dirpath) / d
            if is_reparse_point(child):
                skipped.append(child.relative_to(root).as_posix() + "/")
                continue
            keep_dirs.append(d)
        dirnames[:] = keep_dirs
        for name in filenames:
            p = Path(dirpath) / name
            if is_reparse_point(p):
                skipped.append(p.relative_to(root).as_posix())
                continue
            files.append(p)
            try:
                total += p.stat().st_size
            except OSError:
                pass
            if len(files) > MAX_IMPORT_FILES:
                raise ValueError(
                    f"Refused: folder has more than {MAX_IMPORT_FILES} files."
                )
            if total > MAX_IMPORT_BYTES:
                raise ValueError(
                    f"Refused: folder exceeds {MAX_IMPORT_BYTES} bytes."
                )
    return files, skipped, total


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel_hash_map(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    files, _skipped, _total = _walk_no_reparse(root)
    for p in files:
        rel = p.relative_to(root).as_posix()
        if rel == ORIGIN_FILENAME:
            continue
        out[rel] = _file_sha256(p)
    return out


def workspace_import(folder: str) -> str:
    src = Path(folder).expanduser()
    try:
        src = src.resolve()
    except OSError as exc:
        raise ValueError(f"Cannot resolve folder: {folder} ({exc})") from exc
    if not src.is_dir():
        raise ValueError(f"Not a directory: {folder}")
    if is_reparse_point(src):
        raise ValueError(f"Refused: folder is a junction/symlink: {folder}")
    assert_not_protected(src)
    files, skipped, total = _walk_no_reparse(src)
    name = src.name
    if not name or name in (".", ".."):
        raise ValueError("Cannot derive project name from folder.")
    dest = projects_dir() / name
    skip_preview = "\n".join(f"  - {s}" for s in skipped) if skipped else "  (none)"
    description = (
        f"Import folder into workspace\\projects\\{name}.\n"
        f"Source (read-only): {src}\n"
        f"Files to copy: {len(files)} ({total} bytes)\n"
        f"Skipped directory names: {sorted(SKIP_DIR_NAMES)}\n"
        f"Skipped junctions/symlinks:\n{skip_preview}"
    )
    check_permission(
        action="workspace_import",
        tier=Tier.CONFIRM,
        description=description,
    )
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for f in files:
        rel = f.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    origin = {
        "original": str(src),
        "name": name,
        "imported_files": len(files),
        "skipped_reparse": skipped,
    }
    (dest / ORIGIN_FILENAME).write_text(
        json.dumps(origin, indent=2), encoding="utf-8"
    )
    sha = commit_workspace(f"workspace_import {name}")
    msg = f"Imported {len(files)} file(s) into projects/{name}."
    if skipped:
        msg += f" Skipped junctions/symlinks: {', '.join(skipped)}."
    if sha:
        msg += f" Commit {sha}."
    return msg


def _export_dest(original: Path, name: str) -> Path:
    parent = original.parent
    stamp = date.today().isoformat()
    base = parent / f"{name}-miniai-{stamp}"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = parent / f"{name}-miniai-{stamp}-{n}"
        if not candidate.exists():
            return candidate
        n += 1


def workspace_export(project: str) -> str:
    proj = projects_dir() / project
    if not proj.is_dir():
        raise ValueError(f"No project at workspace/projects/{project}")
    origin_path = proj / ORIGIN_FILENAME
    if not origin_path.is_file():
        raise ValueError(
            f"Project {project} has no origin metadata; cannot export safely."
        )
    origin = json.loads(origin_path.read_text(encoding="utf-8"))
    original = Path(origin["original"])
    if not original.is_dir():
        raise ValueError(f"Original folder no longer exists: {original}")
    before = _rel_hash_map(original)
    after = _rel_hash_map(proj)
    changed: list[str] = []
    for rel, digest in after.items():
        if rel not in before:
            changed.append(f"ADDED {rel}")
        elif before[rel] != digest:
            changed.append(f"CHANGED {rel}")
    for rel in before:
        if rel not in after:
            changed.append(f"REMOVED {rel}")
    dest = _export_dest(original, project)
    preview = "\n".join(changed) if changed else "(no differences vs original)"
    description = (
        f"Export workspace project '{project}' to a NEW sibling folder.\n"
        f"Original (unchanged): {original}\n"
        f"Destination: {dest}\n"
        "Changed/added/removed versus the original:\n"
        f"{preview}"
    )
    check_permission(
        action="workspace_export",
        tier=Tier.CONFIRM,
        description=description,
    )
    dest.mkdir(parents=True)
    files, skipped, _total = _walk_no_reparse(proj)
    copied = 0
    for src_f in files:
        if src_f.name == ORIGIN_FILENAME:
            continue
        rel = src_f.relative_to(proj)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_f, target)
        copied += 1
    msg = (
        f"Exported projects/{project} to {dest} "
        f"({len(changed)} path(s) differ from original; {copied} file(s) copied). "
        "Original folder was not modified."
    )
    if skipped:
        msg += f" Skipped junctions/symlinks: {', '.join(skipped)}."
    return msg


def maybe_auto_run_tests(written_paths: list[str]) -> str | None:
    """Run project tests once via real run_tests (CONFIRM). Return parsed summary.

    Returns None when skipped (no tests / feature off / nothing written).
    On denial or error, returns a short status string.
    """
    from config import settings
    from tools.code.project_discover import infer_test_target
    from tools.code.pytest_summary import parse_pytest_summary

    if not getattr(settings, "FEATURE_CODING_AUTO_TEST", True):
        return None
    if not written_paths:
        return None
    target = infer_test_target(written_paths)
    if not target:
        return None
    from security.gate import PermissionDenied

    try:
        raw = run_tests(path=target)
    except PermissionDenied:
        return f"Auto-test skipped: user denied run_tests on {target}."
    except Exception as exc:
        return f"Auto-test error on {target}: {exc}"
    summary = parse_pytest_summary(raw)
    return f"[Auto-test {target}] {summary}"


# Coding tools that raise the turn round cap (Round 6: 16).
CODING_TOOLS = frozenset(
    {
        "ws_read",
        "ws_list",
        "ws_write",
        "ws_edit",
        "ws_find_project",
        "run_file",
        "run_tests",
        "run_code",
        "install_package",
        "workspace_import",
        "workspace_export",
        "workspace_history",
        "workspace_restore",
    }
)
