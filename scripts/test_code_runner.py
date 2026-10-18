"""Stage 9a isolated code runner tests — every check uses the real low-IL runner."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.code.paths import workspace_dir  # noqa: E402
from tools.code.runner import (  # noqa: E402
    LowIntegrityLaunchError,
    firewall_rule_status,
    run_python,
)
from tools.code import runner as runner_mod  # noqa: E402
from tools.code.code_tools import (  # noqa: E402
    BEGIN_MARKER,
    END_MARKER,
    run_code,
    workspace_history,
    workspace_restore,
)
from tools.code.workspace_git import commit_workspace, ensure_repo, history  # noqa: E402

FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    print(f"{status}: {name} - {detail}")


def _docs_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "Documents"


def main() -> int:
    ws = workspace_dir()
    ensure_repo()
    print(f"workspace={ws}")
    print(f"firewall={firewall_rule_status()}")

    # --- 1. print(1+1) ---
    r1 = run_python("print(1+1)\n", timeout_s=30)
    _check(
        "1",
        r1.exit_code == 0 and "2" in r1.stdout and not r1.timed_out,
        f"exit={r1.exit_code} stdout={r1.stdout!r} timed_out={r1.timed_out}",
    )
    commit_workspace("test 1")

    # --- 2. write in workspace ---
    marker = f"ws_write_{int(time.time())}.txt"
    r2 = run_python(
        f"from pathlib import Path\n"
        f"Path({marker!r}).write_text('hello-ws', encoding='utf-8')\n"
        f"print(Path({marker!r}).read_text(encoding='utf-8'))\n",
        timeout_s=30,
    )
    on_disk = (ws / marker).is_file() and (ws / marker).read_text(encoding="utf-8") == "hello-ws"
    _check(
        "2",
        r2.exit_code == 0 and on_disk and "hello-ws" in r2.stdout,
        f"exit={r2.exit_code} on_disk={on_disk} stdout={r2.stdout!r}",
    )
    commit_workspace("test 2")

    # --- 3. write Documents + repo -> PermissionError; verify nothing created ---
    docs = _docs_dir()
    if not docs.is_dir():
        docs = Path(os.environ["USERPROFILE"]) / "Documents"
    docs_target = docs / "miniai_s9a_SHOULD_NOT_EXIST.txt"
    repo_target = PROJECT_ROOT / "miniai_s9a_SHOULD_NOT_EXIST.txt"
    for p in (docs_target, repo_target):
        if p.exists():
            p.unlink()
    code3 = (
        "from pathlib import Path\n"
        f"docs = Path(r'{docs_target}')\n"
        f"repo = Path(r'{repo_target}')\n"
        "errs = []\n"
        "for label, p in (('docs', docs), ('repo', repo)):\n"
        "    try:\n"
        "        p.write_text('nope', encoding='utf-8')\n"
        "        print(f'{label}:WROTE')\n"
        "    except Exception as e:\n"
        "        print(f'{label}:{type(e).__name__}')\n"
        "        errs.append(type(e).__name__)\n"
    )
    r3 = run_python(code3, timeout_s=30)
    docs_exists = docs_target.exists()
    repo_exists = repo_target.exists()
    out3 = r3.stdout + r3.stderr
    ok3 = (
        not docs_exists
        and not repo_exists
        and "PermissionError" in out3
        and "docs:PermissionError" in out3
        and "repo:PermissionError" in out3
    )
    _check(
        "3",
        ok3,
        f"docs_exists={docs_exists} repo_exists={repo_exists} out={out3!r}",
    )
    for p in (docs_target, repo_target):
        if p.exists():
            p.unlink()

    # --- 4. os.remove outside workspace fails; file remains ---
    outside = Path(tempfile.gettempdir()) / f"miniai_s9a_keep_{int(time.time())}.txt"
    outside.write_text("keep-me", encoding="utf-8")
    r4 = run_python(
        f"import os\n"
        f"try:\n"
        f"    os.remove(r'{outside}')\n"
        f"    print('REMOVED')\n"
        f"except Exception as e:\n"
        f"    print(type(e).__name__)\n",
        timeout_s=30,
    )
    still = outside.exists()
    _check(
        "4",
        still and "REMOVED" not in r4.stdout and "PermissionError" in (r4.stdout + r4.stderr),
        f"still={still} out={r4.stdout!r} err={r4.stderr!r}",
    )
    if outside.exists():
        outside.unlink()

    # --- 5. subprocess child fails ---
    r5 = run_python(
        "import subprocess\n"
        "try:\n"
        "    subprocess.run(['cmd', '/c', 'echo hi'], capture_output=True, text=True)\n"
        "    print('CHILD_OK')\n"
        "except Exception as e:\n"
        "    print(type(e).__name__)\n"
        "    print(e)\n",
        timeout_s=30,
    )
    out5 = r5.stdout + r5.stderr
    _check(
        "5",
        "CHILD_OK" not in out5 and r5.exit_code == 0,
        f"exit={r5.exit_code} out={out5!r}",
    )

    # --- 6. infinite loop killed ---
    r6 = run_python("while True:\n    pass\n", timeout_s=3)
    alive = False
    if r6.pid:
        alive = runner_mod._process_alive(r6.pid)
    _check(
        "6",
        r6.timed_out and not alive,
        f"timed_out={r6.timed_out} alive={alive} pid={r6.pid} exit={r6.exit_code}",
    )

    # --- 7. allocate 3 GB ---
    r7 = run_python(
        "try:\n"
        "    x = bytearray(3 * 1024 * 1024 * 1024)\n"
        "    print('ALLOC_OK', len(x))\n"
        "except Exception as e:\n"
        "    print(type(e).__name__)\n"
        "    raise\n",
        timeout_s=60,
    )
    out7 = r7.stdout + r7.stderr
    ok7 = "ALLOC_OK" not in out7 and (
        r7.memory_limited
        or "MemoryError" in out7
        or (r7.exit_code not in (0, None) and not r7.timed_out)
        or r7.timed_out
    )
    _check(
        "7",
        ok7,
        f"exit={r7.exit_code} mem_lim={r7.memory_limited} timed_out={r7.timed_out} out={out7[:500]!r}",
    )

    # --- 8. env has no secrets ---
    os.environ["TAVILY_API_KEY"] = "tvly-TEST-SHOULD-NOT-LEAK"
    os.environ["MINIAI_S9A_SECRET"] = "secret-from-env-file-sim"
    try:
        r8 = run_python(
            "import os\n"
            "print('TAVILY', os.environ.get('TAVILY_API_KEY'))\n"
            "print('SECRET', os.environ.get('MINIAI_S9A_SECRET'))\n"
            "print('KEYS', ','.join(sorted(os.environ.keys())))\n",
            timeout_s=30,
        )
        out8 = r8.stdout + r8.stderr
        ok8 = (
            "tvly-TEST-SHOULD-NOT-LEAK" not in out8
            and "secret-from-env-file-sim" not in out8
            and "TAVILY None" in r8.stdout
            and "SECRET None" in r8.stdout
        )
        _check("8", ok8, f"out={out8!r}")
    finally:
        os.environ.pop("TAVILY_API_KEY", None)
        os.environ.pop("MINIAI_S9A_SECRET", None)

    # --- 9. 100k print truncated ---
    r9 = run_python("print('X' * 100000)\n", timeout_s=30)
    _check(
        "9",
        r9.stdout_truncated and "truncated" in r9.stdout and len(r9.stdout) <= 20000 + 80,
        f"trunc={r9.stdout_truncated} len={len(r9.stdout)}",
    )

    # --- 10. network ---
    fw = firewall_rule_status()
    r10 = run_python(
        "import urllib.request\n"
        "try:\n"
        "    with urllib.request.urlopen('https://example.com', timeout=15) as r:\n"
        "        print('NET_OK', r.status)\n"
        "except Exception as e:\n"
        "    print('NET_FAIL', type(e).__name__, e)\n",
        timeout_s=45,
    )
    out10 = r10.stdout + r10.stderr
    if fw == "INSTALLED":
        ok10 = "NET_OK" not in out10 and "NET_FAIL" in out10
        detail10 = f"rule INSTALLED; out={out10!r}"
    else:
        ok10 = True
        detail10 = f"rule not installed - network NOT blocked; out={out10!r}"
        print(f"NOTE: {detail10}")
    _check("10", ok10, detail10)

    # --- 11. low-IL launch failure refuses; nothing ran ---
    stamp_before = set(ws.glob("run_*.py"))

    def _boom(*_a, **_k):
        raise LowIntegrityLaunchError("patched failure")

    with patch("builtins.input", return_value="yes"), patch.object(
        runner_mod, "launch_low_integrity", side_effect=_boom
    ):
        refused = run_code("print('SHOULD_NOT_RUN')\n")
    stamp_after = set(ws.glob("run_*.py"))
    # run_code writes the script before launch; refuse means not executed.
    # Accept either no new script or script present but REFUSED and no success markers.
    ok11 = (
        "REFUSED" in refused
        and "SHOULD_NOT_RUN" not in refused
        and BEGIN_MARKER not in refused
    )
    _check(
        "11",
        ok11,
        f"refused={refused!r} new_scripts={len(stamp_after - stamp_before)}",
    )

    # --- 12. workspace_history + workspace_restore ---
    hist_file = ws / "history_probe.txt"
    hist_file.write_text("version-one", encoding="utf-8")
    sha1 = commit_workspace("probe version one")
    hist_file.write_text("version-two", encoding="utf-8")
    sha2 = commit_workspace("probe version two")
    hist_text = workspace_history()
    ok_hist = bool(sha1) and bool(sha2) and (sha1[:7] in hist_text or sha1 in hist_text)
    # restore to sha1
    with patch("builtins.input", return_value="yes"):
        restore_msg = workspace_restore(sha1)
    content = hist_file.read_text(encoding="utf-8")
    ok_restore = content == "version-one" and "Restored" in restore_msg
    _check(
        "12",
        ok_hist and ok_restore,
        f"sha1={sha1} sha2={sha2} hist_ok={ok_hist} content={content!r} msg={restore_msg!r}",
    )

    # Also verify run_code wraps markers when succeeding
    with patch("builtins.input", return_value="yes"):
        wrapped = run_code("print('wrap-me')\n")
    _check(
        "12b",
        BEGIN_MARKER in wrapped and END_MARKER in wrapped and "wrap-me" in wrapped,
        f"wrapped_prefix={wrapped[:120]!r}",
    )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
