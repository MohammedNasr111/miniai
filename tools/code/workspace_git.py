"""Git versioning for the isolated code workspace (MiniAI-owned commits)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from tools.code.paths import ensure_workspace, workspace_dir

GIT_AUTHOR_NAME = "MiniAI"
GIT_AUTHOR_EMAIL = "miniai@local"


class WorkspaceGitError(RuntimeError):
    pass


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = GIT_AUTHOR_NAME
    env["GIT_AUTHOR_EMAIL"] = GIT_AUTHOR_EMAIL
    env["GIT_COMMITTER_NAME"] = GIT_AUTHOR_NAME
    env["GIT_COMMITTER_EMAIL"] = GIT_AUTHOR_EMAIL
    return env


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_env(),
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise WorkspaceGitError("git is not installed or not on PATH.") from exc
    if check and cp.returncode != 0:
        raise WorkspaceGitError(
            f"git {' '.join(args)} failed ({cp.returncode}): "
            f"{(cp.stderr or cp.stdout or '').strip()}"
        )
    return cp


def ensure_repo() -> Path:
    ws = ensure_workspace()
    git_dir = ws / ".git"
    if not git_dir.exists():
        _run_git(["init"], ws)
        # Ignore tmp/ scratch; keep run scripts and user files.
        ignore = ws / ".gitignore"
        if not ignore.exists():
            ignore.write_text("tmp/\n", encoding="utf-8")
        _run_git(["add", ".gitignore"], ws, check=False)
        _run_git(
            ["commit", "--allow-empty", "-m", "Initial MiniAI workspace"],
            ws,
            check=False,
        )
    return ws


def is_under_workspace(path: str | Path) -> bool:
    try:
        ws = workspace_dir().resolve()
        target = Path(path).expanduser().resolve()
    except OSError:
        return False
    ws_s = os.path.normcase(str(ws))
    t_s = os.path.normcase(str(target))
    return t_s == ws_s or t_s.startswith(ws_s + os.sep)


def commit_workspace(message: str) -> Optional[str]:
    """git add -A && git commit in the workspace. Returns commit hash or None if nothing to commit."""
    ws = ensure_repo()
    _run_git(["add", "-A"], ws)
    status = _run_git(["status", "--porcelain"], ws)
    if not (status.stdout or "").strip():
        return None
    # Truncate message for safety.
    msg = " ".join(message.split())[:200] or "workspace update"
    _run_git(["commit", "-m", msg], ws)
    sha = _run_git(["rev-parse", "HEAD"], ws)
    return (sha.stdout or "").strip() or None


def maybe_commit_workspace_path(path: str | Path, message: str) -> Optional[str]:
    if is_under_workspace(path):
        return commit_workspace(message)
    return None


def history(limit: int = 20) -> str:
    ws = ensure_repo()
    cp = _run_git(
        ["log", f"-{int(limit)}", "--pretty=format:%h %ci %s"],
        ws,
        check=False,
    )
    if cp.returncode != 0:
        return "(no commits yet)"
    text = (cp.stdout or "").strip()
    return text if text else "(no commits yet)"


def files_changed_by_restore(commit: str) -> list[str]:
    """Paths that differ between HEAD working tree and commit (for restore preview)."""
    ws = ensure_repo()
    commit = commit.strip()
    if not commit:
        raise WorkspaceGitError("commit is required")
    # Validate commit exists.
    _run_git(["rev-parse", "--verify", commit], ws)
    cp = _run_git(["diff", "--name-status", "HEAD", commit], ws, check=False)
    lines = [ln for ln in (cp.stdout or "").splitlines() if ln.strip()]
    # Also include uncommitted changes that restore would overwrite.
    dirty = _run_git(["status", "--porcelain"], ws, check=False)
    for ln in (dirty.stdout or "").splitlines():
        if ln.strip():
            lines.append(f"DIRTY {ln[3:].strip()}")
    return lines


def restore(commit: str) -> str:
    """Restore working tree files from commit without deleting history."""
    ws = ensure_repo()
    commit = commit.strip()
    _run_git(["rev-parse", "--verify", commit], ws)
    # Restore tracked files from that commit into the working tree / index.
    _run_git(["checkout", commit, "--", "."], ws)
    # Commit the restore as a new MiniAI commit so history is preserved.
    sha = commit_workspace(f"Restore workspace from {commit}")
    return sha or commit
