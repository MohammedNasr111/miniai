"""Discover coding projects in the workspace and create per-task slug folders."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from security.gate import Tier, check_permission
from tools.code.paths import workspace_dir
from tools.code.workspace_paths import resolve_in_workspace

SKIP_DIR_NAMES = {"node_modules", ".venv", "__pycache__"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


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
_CODING_HINT = re.compile(
    r"(?i)\b("
    r"code|coding|python|pytest|debug|fix|bug|implement|build|write\s+a\s+"
    r"(?:script|program|module|package|cli|tool)|expense|tracker|refactor"
    r")\b"
)
_NEW_PROJECT = re.compile(
    r"(?i)\b("
    r"build|create|implement|make|write|scaffold|generate"
    r")\b"
)
_DEBUG_EXISTING = re.compile(
    r"(?i)\b(debug|fix|failing|fails|broken|bug in|does not pass|tests?\s+fail)\b"
)


def slugify(text: str, *, max_len: int = 40) -> str:
    s = (text or "").strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    if not s:
        s = "project"
    return s[:max_len].rstrip("-") or "project"


def looks_like_coding_request(text: str) -> bool:
    return bool(_CODING_HINT.search(text or ""))


def _has_project_markers(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    names = set(os.listdir(folder))
    if "pyproject.toml" in names:
        return True
    if any(n.startswith("requirements") and n.endswith(".txt") for n in names):
        return True
    if "tests" in names or "test" in names:
        return True
    # Any test_*.py at this level
    for n in names:
        if n.startswith("test_") and n.endswith(".py"):
            return True
        if n.endswith("_test.py"):
            return True
    # Has .py files AND a nested tests dir
    py_here = any(n.endswith(".py") for n in names)
    if py_here and _list_test_files(folder):
        return True
    return False


def _count_files(folder: Path, *, limit: int = 5000) -> tuple[int, float]:
    n = 0
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [
            d for d in dirnames if d not in SKIP_DIR_NAMES and d != ".git"
        ]
        for name in filenames:
            n += 1
            if n >= limit:
                break
            try:
                m = (Path(dirpath) / name).stat().st_mtime
                if m > newest:
                    newest = m
            except OSError:
                pass
        if n >= limit:
            break
    return n, newest


def list_project_candidates(hint: str = "") -> list[dict[str, Any]]:
    """Return candidate project roots under the workspace."""
    ws = workspace_dir()
    ws.mkdir(parents=True, exist_ok=True)
    hint_l = (hint or "").strip().lower()
    seen: set[Path] = set()
    cands: list[dict[str, Any]] = []

    def _add(folder: Path, reason: str) -> None:
        try:
            folder = folder.resolve()
        except OSError:
            return
        if folder in seen or not folder.is_dir():
            return
        # Must be under workspace
        try:
            folder.relative_to(ws.resolve())
        except ValueError:
            return
        seen.add(folder)
        n_files, newest = _count_files(folder)
        rel = str(folder.relative_to(ws)).replace("\\", "/")
        if rel == ".":
            rel = "."
        score = newest
        if hint_l:
            if hint_l in rel.lower() or hint_l in folder.name.lower():
                score += 1e12
            # token overlap
            for tok in re.split(r"[^a-z0-9]+", hint_l):
                if tok and tok in folder.name.lower():
                    score += 1e9
        cands.append(
            {
                "path": rel,
                "abs": str(folder),
                "file_count": n_files,
                "newest_mtime": newest,
                "newest_iso": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(newest)
                )
                if newest
                else None,
                "reason": reason,
                "_score": score,
            }
        )

    # Direct children that look like projects
    try:
        children = sorted(ws.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or child.name in SKIP_DIR_NAMES or child.name == ".git":
            continue
        if child.name.startswith("."):
            continue
        if _has_project_markers(child) or list(child.glob("*.py")):
            # Prefer dirs with py + tests markers
            if _has_project_markers(child) or _list_test_files(child):
                _add(child, "project_markers")
            elif any(child.glob("*.py")):
                _add(child, "python_folder")

    # Workspace root itself if it has tests + py
    if _list_test_files(ws) and any(ws.glob("*.py")) or (ws / "buggy").is_dir():
        # Also surface common sibling layout: buggy/ + tests/
        if (ws / "buggy").is_dir():
            _add(ws / "buggy", "buggy_layout")
        if (ws / "tests").is_dir() and _list_test_files(ws / "tests"):
            _add(ws, "workspace_root_tests")

    # projects/ imports
    proj = ws / "projects"
    if proj.is_dir():
        for child in proj.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                _add(child, "projects_import")

    cands.sort(key=lambda c: (-c["_score"], c["path"]))
    for c in cands:
        c.pop("_score", None)
    return cands


def ws_find_project(hint: str = "") -> str:
    """List candidate project roots in the workspace (AUTO_ALLOW).

    If the user names a project or folder, call ws_find_project first.
    """
    check_permission(
        action="ws_find_project",
        tier=Tier.AUTO_ALLOW,
        description=f"Find project in workspace (hint={hint!r})",
    )
    cands = list_project_candidates(hint)
    if not cands:
        return (
            "No project candidates found under the workspace. "
            "Create a new folder with ws_write (e.g. myapp/main.py)."
        )
    lines = [f"Found {len(cands)} project candidate(s):"]
    for i, c in enumerate(cands[:12], 1):
        lines.append(
            f"{i}. {c['path']}  files={c['file_count']}  "
            f"newest={c['newest_iso'] or 'n/a'}  ({c['reason']})"
        )
    if hint:
        lines.append(f"Hint used for ranking: {hint!r}")
    lines.append(
        "Prefer the top match. Write/edit under that path; "
        "do not scatter new files at the workspace root."
    )
    return "\n".join(lines)


_EXPLICIT_FOLDER = re.compile(
    r"(?:under\s+(?:the\s+)?folder|in\s+(?:the\s+)?(?:folder|directory)|"
    r"folder\s+called|directory\s+called|project\s+folder)\s+"
    r"[`'\"]?([A-Za-z][\w\-]{1,64})[`'\"]?"
    r"|"
    r"\b([A-Za-z][\w\-]{1,64})/(?:[\w.\-]+(?:\.py)?|tests)\b",
    re.I,
)


def ensure_task_slug_folder(user_text: str) -> Optional[str]:
    """Create workspace/<slug>/ for a new coding request; leave existing files alone.

    Returns the relative slug path if created (or already present empty-ish),
    else None when the request should use an existing discovered project.
    """
    text = user_text or ""
    if not looks_like_coding_request(text):
        return None
    # Debug/fix existing code → do not create a new folder.
    if _DEBUG_EXISTING.search(text) and not _NEW_PROJECT.search(text):
        return None
    # Only for clearly-new project requests.
    if not _NEW_PROJECT.search(text):
        return None
    # Prefer an explicitly named folder (e.g. "under the folder eval_wordcount").
    # Keep underscores — graders and prompts use literal folder names.
    m = _EXPLICIT_FOLDER.search(text)
    if m:
        raw = next(g for g in m.groups() if g)
        slug = re.sub(r"[^\w\-]+", "-", raw.strip()).strip("-")[:40] or "project"
        ws = workspace_dir()
        target = ws / slug
        target.mkdir(parents=True, exist_ok=True)
        return slug
    # If the user clearly names an existing project folder, reuse it.
    cands = list_project_candidates(text)
    if cands:
        top = cands[0]
        rel = (top.get("path") or "").replace("\\", "/").strip(".")
        if rel and top["file_count"] > 0 and any(
            tok and tok in rel.lower()
            for tok in re.split(r"[^a-z0-9]+", text.lower())
            if len(tok) > 3
        ):
            return None
    # Build slug from distinctive words
    words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text)
    skip = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "please",
        "build",
        "write",
        "create",
        "make",
        "implement",
        "python",
        "code",
        "project",
        "simple",
        "using",
        "tests",
        "test",
        "file",
        "files",
        "pytest",
        "sqlite",
    }
    picked = [w.lower() for w in words if w.lower() not in skip][:4]
    slug = slugify("-".join(picked) if picked else "coding-task")
    ws = workspace_dir()
    target = ws / slug
    # Never clobber an existing non-empty tree — pick a free name.
    if target.exists() and any(target.iterdir()):
        n = 2
        while (ws / f"{slug}-{n}").exists():
            n += 1
        slug = f"{slug}-{n}"
        target = ws / slug
    target.mkdir(parents=True, exist_ok=True)
    return slug


def infer_test_target(written_paths: list[str]) -> Optional[str]:
    """Pick a workspace-relative pytest path for edited files, if tests exist."""
    ws = workspace_dir().resolve()
    checked: set[Path] = set()
    for rel in written_paths:
        try:
            p = resolve_in_workspace(rel)
        except Exception:
            continue
        # Walk up from the file's directory toward workspace
        cur = p if p.is_dir() else p.parent
        while True:
            try:
                cur.relative_to(ws)
            except ValueError:
                break
            if cur in checked:
                break
            checked.add(cur)
            tests_dir = cur / "tests"
            if tests_dir.is_dir() and _list_test_files(tests_dir):
                return str(tests_dir.relative_to(ws)).replace("\\", "/")
            if _list_test_files(cur):
                # test_*.py living next to the code
                return str(cur.relative_to(ws)).replace("\\", "/") or "."
            if cur == ws:
                break
            cur = cur.parent
    # Workspace-root tests (debug fixture layout)
    root_tests = ws / "tests"
    if root_tests.is_dir() and _list_test_files(root_tests):
        return "tests"
    return None
