"""Git versioning for the isolated code workspace (MiniAI-owned commits).

Git metadata lives under %LOCALAPPDATA%\\MiniAI\\workspace-git (medium IL),
not inside the low-IL workspace. Every invocation disables hooks, fsmonitor,
protocol helpers, and user/system gitconfig. The repo config file is written
from an allowlist and verified before every git call.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config.proc import hidden_subprocess_kwargs
from tools.code.paths import (
    ensure_workspace,
    miniai_data_home,
    workspace_dir,
    workspace_git_dir,
)

GIT_AUTHOR_NAME = "MiniAI"
GIT_AUTHOR_EMAIL = "miniai@local"

HISTORY_PAUSED_MSG = (
    "Workspace history settings were changed unexpectedly; history is paused"
)

# Only these keys may appear in the external git dir's config file.
ALLOWED_CONFIG: dict[str, str] = {
    "core.repositoryformatversion": "0",
    "core.bare": "false",
    "core.hooksPath": "NUL",
    "core.fsmonitor": "false",
    "core.autocrlf": "false",
    "user.name": GIT_AUTHOR_NAME,
    "user.email": GIT_AUTHOR_EMAIL,
}

# Keys git/MiniAI used to leave in the config before the allowlist rewrite;
# safe to discard on upgrade. Anything else (filters, hooksPath overrides as
# separate keys, etc.) is left in place so verify_git_config refuses.
_LEGACY_EXTRA_KEYS = frozenset(
    {
        "core.worktree",
        "core.filemode",
        "core.logallrefupdates",
        "core.symlinks",
        "core.ignorecase",
    }
)

# Set by ensure_repo when migrating away from workspace\\.git.
_MIGRATION_NOTE = ""


class WorkspaceGitError(RuntimeError):
    pass


def migration_note() -> str:
    return _MIGRATION_NOTE


def git_dir() -> Path:
    return workspace_git_dir()


def _safe_git_prefix(git_dir_path: Path, work_tree: Path) -> list[str]:
    return [
        "git",
        f"--git-dir={git_dir_path}",
        f"--work-tree={work_tree}",
        "-c",
        "core.hooksPath=NUL",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.attributesFile=NUL",
        "-c",
        "protocol.allow=never",
        "-c",
        "core.sshCommand=false",
    ]


def _git_env() -> dict[str, str]:
    """Minimal environment: no inherited GIT_* ; no user/system config."""
    home = str(miniai_data_home())
    miniai_data_home().mkdir(parents=True, exist_ok=True)
    systemroot = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or r"C:\Windows"
    path = os.environ.get("PATH", "")
    return {
        "SYSTEMROOT": systemroot,
        "WINDIR": systemroot,
        "PATH": path,
        "TEMP": os.environ.get("TEMP") or home,
        "TMP": os.environ.get("TMP") or home,
        "HOME": home,
        "USERPROFILE": home,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "NUL",
        "GIT_AUTHOR_NAME": GIT_AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": GIT_AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": GIT_AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": GIT_AUTHOR_EMAIL,
    }


def _write_allowed_config(gd: Path) -> None:
    """Replace the git config file with only allowlisted keys/values."""
    gd.mkdir(parents=True, exist_ok=True)
    text = (
        "[core]\n"
        "\trepositoryformatversion = 0\n"
        "\tbare = false\n"
        "\thooksPath = NUL\n"
        "\tfsmonitor = false\n"
        "\tautocrlf = false\n"
        "[user]\n"
        f"\tname = {GIT_AUTHOR_NAME}\n"
        f"\temail = {GIT_AUTHOR_EMAIL}\n"
    )
    (gd / "config").write_text(text, encoding="utf-8")


def _list_config_entries(gd: Path) -> list[tuple[str, str]]:
    """Return (key, value) pairs from the external config via git config --file."""
    cfg = gd / "config"
    if not cfg.is_file():
        raise WorkspaceGitError(HISTORY_PAUSED_MSG)
    try:
        cp = subprocess.run(
            ["git", "config", "--file", str(cfg), "--list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_env(),
            timeout=30,
            **hidden_subprocess_kwargs(),
        )
    except FileNotFoundError as exc:
        raise WorkspaceGitError("git is not installed or not on PATH.") from exc
    if cp.returncode != 0:
        raise WorkspaceGitError(HISTORY_PAUSED_MSG)
    entries: list[tuple[str, str]] = []
    for line in (cp.stdout or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        entries.append((key.strip(), val.strip()))
    return entries


def _config_keys_lower(gd: Path) -> set[str]:
    return {k.lower() for k, _ in _list_config_entries(gd)}


def verify_git_config(gd: Optional[Path] = None) -> None:
    """Refuse if the external config has any key outside the allowlist."""
    path = gd or workspace_git_dir()
    allowed = {k.lower() for k in ALLOWED_CONFIG}
    try:
        keys = _config_keys_lower(path)
    except WorkspaceGitError:
        raise
    except OSError as exc:
        raise WorkspaceGitError(HISTORY_PAUSED_MSG) from exc
    extra = keys - allowed
    if extra:
        raise WorkspaceGitError(HISTORY_PAUSED_MSG)


def _normalize_legacy_config(gd: Path) -> None:
    """Rewrite allowlist config when safe (legacy extras or missing required keys)."""
    try:
        keys = _config_keys_lower(gd)
    except WorkspaceGitError:
        _write_allowed_config(gd)
        return
    allowed = {k.lower() for k in ALLOWED_CONFIG}
    extra = keys - allowed
    missing = allowed - keys
    if extra and not (extra <= {k.lower() for k in _LEGACY_EXTRA_KEYS}):
        # Unknown keys present — leave them for verify_git_config to refuse.
        return
    if extra or missing:
        _write_allowed_config(gd)


def _run_git(
    args: list[str],
    *,
    check: bool = True,
    git_dir_path: Optional[Path] = None,
    work_tree: Optional[Path] = None,
    skip_verify: bool = False,
) -> subprocess.CompletedProcess:
    gd = git_dir_path or workspace_git_dir()
    wt = work_tree or workspace_dir()
    if not skip_verify:
        verify_git_config(gd)
    cmd = _safe_git_prefix(gd, wt) + args
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(wt),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_env(),
            timeout=120,
            **hidden_subprocess_kwargs(),
        )
    except FileNotFoundError as exc:
        raise WorkspaceGitError("git is not installed or not on PATH.") from exc
    if check and cp.returncode != 0:
        raise WorkspaceGitError(
            f"git {' '.join(args)} failed ({cp.returncode}): "
            f"{(cp.stderr or cp.stdout or '').strip()}"
        )
    return cp


def _ensure_exclude(gd: Path) -> None:
    info = gd / "info"
    info.mkdir(parents=True, exist_ok=True)
    exclude = info / "exclude"
    required = [".git/", "tmp/", ".git"]
    existing = ""
    if exclude.is_file():
        existing = exclude.read_text(encoding="utf-8", errors="replace")
    lines = existing.splitlines()
    changed = False
    for item in required:
        if item not in lines:
            lines.append(item)
            changed = True
    if changed or not exclude.is_file():
        exclude.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _init_fresh(gd: Path, ws: Path) -> None:
    gd.parent.mkdir(parents=True, exist_ok=True)
    if gd.exists():
        _rmtree(gd)
    cmd = [
        "git",
        "-c",
        "core.hooksPath=NUL",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.attributesFile=NUL",
        "-c",
        "protocol.allow=never",
        "-c",
        "core.sshCommand=false",
        "init",
        "--bare",
        str(gd),
    ]
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_git_env(),
        timeout=60,
        **hidden_subprocess_kwargs(),
    )
    if cp.returncode != 0:
        raise WorkspaceGitError(
            f"git init --bare failed: {(cp.stderr or cp.stdout or '').strip()}"
        )
    # Discard whatever init wrote; install allowlisted config only.
    _write_allowed_config(gd)
    _ensure_exclude(gd)
    ignore = ws / ".gitignore"
    if not ignore.exists():
        ignore.write_text("tmp/\n.git/\n", encoding="utf-8")
    _run_git(["add", "-A"], git_dir_path=gd, work_tree=ws, check=False)
    _run_git(
        ["commit", "--allow-empty", "-m", "Initial MiniAI workspace"],
        git_dir_path=gd,
        work_tree=ws,
        check=False,
    )


def _sanitize_copied_git_dir(gd: Path) -> None:
    """Strip hooks from a copied git directory; config is rewritten separately."""
    hooks = gd / "hooks"
    if hooks.exists():
        shutil.rmtree(hooks, ignore_errors=True)
    hooks.mkdir(parents=True, exist_ok=True)
    for p in hooks.glob("*"):
        try:
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def _migrate_from_workspace_git(old_git: Path, gd: Path, ws: Path) -> bool:
    """Import history from workspace\\.git; discard migrated config entirely."""
    gd.parent.mkdir(parents=True, exist_ok=True)
    if gd.exists():
        _rmtree(gd)
    try:
        if old_git.is_file():
            text = old_git.read_text(encoding="utf-8", errors="replace").strip()
            if text.lower().startswith("gitdir:"):
                real = Path(text.split(":", 1)[1].strip())
                if not real.is_absolute():
                    real = (old_git.parent / real).resolve()
                shutil.copytree(real, gd)
            else:
                return False
        else:
            shutil.copytree(old_git, gd)
    except OSError:
        return False
    _sanitize_copied_git_dir(gd)
    # Discard migrated config; write allowlist from scratch.
    _write_allowed_config(gd)
    _ensure_exclude(gd)
    try:
        cp = _run_git(
            ["rev-parse", "--git-dir"], git_dir_path=gd, work_tree=ws, check=False
        )
        if cp.returncode != 0:
            return False
    except WorkspaceGitError:
        return False
    return True


def _clear_readonly(path: Path) -> None:
    try:
        if path.exists():
            os.chmod(path, 0o700)
    except OSError:
        pass


def _rmtree(path: Path) -> None:
    if not path.exists():
        return

    def _onexc(func, p, _exc):
        _clear_readonly(Path(p))
        try:
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onexc=_onexc)
    if path.exists():
        subprocess.run(
            ["cmd", "/c", "rmdir", "/s", "/q", str(path)],
            capture_output=True,
            timeout=60,
            **hidden_subprocess_kwargs(),
        )


def _delete_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir() and not path.is_symlink():
        _rmtree(path)
    else:
        _clear_readonly(path)
        try:
            path.unlink()
        except OSError:
            pass
    if path.exists():
        subprocess.run(
            ["cmd", "/c", "rmdir", "/s", "/q", str(path)],
            capture_output=True,
            timeout=60,
            **hidden_subprocess_kwargs(),
        )


def ensure_repo() -> Path:
    """Ensure external git dir is ready; migrate/delete workspace\\.git if present."""
    global _MIGRATION_NOTE
    ws = ensure_workspace()
    gd = workspace_git_dir()
    old = ws / ".git"

    if gd.exists() and (gd / "HEAD").exists():
        _ensure_exclude(gd)
        _sanitize_copied_git_dir(gd)
        _normalize_legacy_config(gd)
        if old.exists():
            _delete_path(old)
        return ws

    if old.exists():
        ok = _migrate_from_workspace_git(old, gd, ws)
        if ok:
            _MIGRATION_NOTE = (
                f"Migrated workspace git history from {old} to {gd}."
            )
            _delete_path(old)
            if old.exists():
                _MIGRATION_NOTE += f" Warning: could not fully delete {old}."
        else:
            _MIGRATION_NOTE = (
                f"Migration from {old} failed; started fresh history at {gd}."
            )
            _init_fresh(gd, ws)
            _delete_path(old)
        return ws

    _MIGRATION_NOTE = f"Initialized new workspace git at {gd}."
    _init_fresh(gd, ws)
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
    """git add -A && git commit. Returns commit hash or None if nothing to commit."""
    ws = ensure_repo()
    gd = workspace_git_dir()
    _run_git(["add", "-A"], git_dir_path=gd, work_tree=ws)
    status = _run_git(["status", "--porcelain"], git_dir_path=gd, work_tree=ws)
    if not (status.stdout or "").strip():
        return None
    msg = " ".join(message.split())[:200] or "workspace update"
    _run_git(["commit", "-m", msg], git_dir_path=gd, work_tree=ws)
    sha = _run_git(["rev-parse", "HEAD"], git_dir_path=gd, work_tree=ws)
    return (sha.stdout or "").strip() or None


def maybe_commit_workspace_path(path: str | Path, message: str) -> Optional[str]:
    if is_under_workspace(path):
        return commit_workspace(message)
    return None


def history(limit: int = 20) -> str:
    ws = ensure_repo()
    gd = workspace_git_dir()
    cp = _run_git(
        ["log", f"-{int(limit)}", "--pretty=format:%h %ci %s"],
        git_dir_path=gd,
        work_tree=ws,
        check=False,
    )
    if cp.returncode != 0:
        return "(no commits yet)"
    text = (cp.stdout or "").strip()
    return text if text else "(no commits yet)"


def files_changed_by_restore(commit: str) -> list[str]:
    ws = ensure_repo()
    gd = workspace_git_dir()
    commit = commit.strip()
    if not commit:
        raise WorkspaceGitError("commit is required")
    _run_git(["rev-parse", "--verify", commit], git_dir_path=gd, work_tree=ws)
    cp = _run_git(
        ["diff", "--name-status", "HEAD", commit],
        git_dir_path=gd,
        work_tree=ws,
        check=False,
    )
    lines = [ln for ln in (cp.stdout or "").splitlines() if ln.strip()]
    dirty = _run_git(
        ["status", "--porcelain"], git_dir_path=gd, work_tree=ws, check=False
    )
    for ln in (dirty.stdout or "").splitlines():
        if ln.strip():
            lines.append(f"DIRTY {ln[3:].strip()}")
    return lines


def restore(commit: str) -> str:
    """Restore working tree files from commit without deleting history."""
    ws = ensure_repo()
    gd = workspace_git_dir()
    commit = commit.strip()
    _run_git(["rev-parse", "--verify", commit], git_dir_path=gd, work_tree=ws)
    _run_git(["checkout", commit, "--", "."], git_dir_path=gd, work_tree=ws)
    sha = commit_workspace(f"Restore workspace from {commit}")
    return sha or commit


def hash_git_config() -> str:
    """SHA-256 of the external git config file (for escape-test integrity)."""
    import hashlib

    ensure_repo()
    cfg = workspace_git_dir() / "config"
    if not cfg.is_file():
        return ""
    return hashlib.sha256(cfg.read_bytes()).hexdigest()
