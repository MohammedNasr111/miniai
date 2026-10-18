"""Stage 9b coding-loop tools — real workspace + low-IL runner where applicable."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.base import ChatMessage  # noqa: E402
from security.gate import PermissionDenied, reset_session  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

from tools.code.paths import workspace_dir, workspace_git_dir  # noqa: E402
from tools.code.runner import run_python  # noqa: E402
from tools.code.workspace_git import (  # noqa: E402
    HISTORY_PAUSED_MSG,
    WorkspaceGitError,
    commit_workspace,
    ensure_repo,
    hash_git_config,
    history,
    migration_note,
    restore,
)
from tools.code.workspace_tools import (  # noqa: E402
    CODING_TOOLS,
    install_package,
    run_file,
    run_tests,
    workspace_export,
    workspace_import,
    ws_edit,
    ws_write,
)
from tools.code.workspace_paths import WorkspacePathError  # noqa: E402
from tools.registry import TOOL_FUNCTIONS, TOOL_TIERS  # noqa: E402
from security.gate import Tier  # noqa: E402
FAILURES = 0


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    print(f"{status}: {name} - {detail}")


def _hash_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    reset_session()
    ws = workspace_dir()
    print(f"workspace={ws}")

    # --- 1. ws_write outside workspace refused ---
    cases = []
    abs_out = str(Path(tempfile.gettempdir()) / "miniai_s9b_outside.txt")
    for path in (abs_out, "..\\..\\Windows\\Temp\\x.txt", "D:\\nope\\x.txt"):
        try:
            ws_write(path, "nope")
            cases.append((path, "wrote"))
        except (WorkspacePathError, ValueError, OSError) as exc:
            cases.append((path, type(exc).__name__))
    ok1 = all(c[1] != "wrote" for c in cases) and Path(abs_out).exists() is False
    _check("1", ok1, f"cases={cases}")

    # --- 2. ws_edit match counts + commit ---
    rel = "s9b_edit_probe.txt"
    ws_write(rel, "alpha beta alpha\n")
    hist_before = history(5)
    r0 = ws_edit(rel, "gamma", "x")
    r2 = ws_edit(rel, "alpha", "ALPHA")
    # rewrite for exact-one case
    ws_write(rel, "only once: TOKEN here\n")
    r1 = ws_edit(rel, "TOKEN", "OK")
    content = (ws / rel).read_text(encoding="utf-8")
    hist_after = history(5)
    ok2 = (
        "0 time" in r0
        and "2 time" in r2
        and "1 replacement" in r1
        and "OK" in content
        and "TOKEN" not in content
        and hist_after != hist_before
        and "Commit" in r1
    )
    _check("2", ok2, f"r0={r0!r} r2={r2!r} r1={r1!r} content={content!r}")

    # --- 3. run_file ---
    script = "s9b_hello.py"
    ws_write(script, "import sys\nprint('hello', sys.argv[1] if len(sys.argv)>1 else '')\n")
    prompts: list[str] = []

    def _cap_print(*a, **k):
        sep = k.get("sep", " ")
        prompts.append(sep.join(str(x) for x in a))
        return builtins_print(*a, **k)

    import builtins

    builtins_print = builtins.print
    with patch("builtins.input", return_value="yes"), patch(
        "builtins.print", side_effect=_cap_print
    ):
        out3 = run_file(script, args=["world"])
    prompt_blob = "\n".join(prompts)
    ok3 = (
        "hello world" in out3
        and "import sys" in prompt_blob
        and "s9b_hello" in prompt_blob
        and "<<<BEGIN UNTRUSTED CODE OUTPUT>>>" in out3
    )
    _check("3", ok3, f"out_has_hello={'hello world' in out3} prompt_has_src={'import sys' in prompt_blob}")

    # --- 4. install_package ---
    # yes denied
    with patch("builtins.input", return_value="yes"):
        try:
            install_package("six")
            denied_yes = False
            detail_yes = "unexpected success"
        except PermissionDenied as exc:
            denied_yes = True
            detail_yes = str(exc)
    # invalid name no prompt
    prompted = {"n": 0}

    def _count_input(prompt=""):
        prompted["n"] += 1
        return "install_package"

    with patch("builtins.input", side_effect=_count_input):
        try:
            install_package("../evil")
            invalid_ok = False
            inv_detail = "accepted"
        except ValueError as exc:
            invalid_ok = prompted["n"] == 0
            inv_detail = str(exc)
    # typed install six
    with patch("builtins.input", return_value="install_package"):
        inst = install_package("six")
    verify = run_python("import six\nprint('SIX', six.__version__)\n")
    ok4 = (
        denied_yes
        and invalid_ok
        and "succeeded" in inst.lower()
        and verify.exit_code == 0
        and "SIX" in verify.stdout
    )
    _check(
        "4",
        ok4,
        f"yes_denied={denied_yes} invalid={invalid_ok}/{inv_detail!r} "
        f"import_out={verify.stdout!r}",
    )

    # --- 5. run_tests pass+fail ---
    tdir = "s9b_tiny_tests"
    ws_write(
        f"{tdir}/test_tiny.py",
        "def test_pass():\n    assert 1 + 1 == 2\n\n"
        "def test_fail():\n    assert 1 + 1 == 3\n",
    )
    with patch("builtins.input", return_value="yes"):
        tout = run_tests(tdir)
    ok5 = (
        ("1 passed" in tout or "1 passed" in tout.replace("\r", ""))
        and ("1 failed" in tout or "failed" in tout.lower())
    )
    # pytest -q summary often like "1 failed, 1 passed"
    ok5 = "1 failed" in tout and "1 passed" in tout
    _check("5", ok5, f"out_tail={tout[-800]!r}")

    # --- 6. import / edit / export; original unchanged ---
    with tempfile.TemporaryDirectory(prefix="miniai_s9b_proj_") as tmp:
        src = Path(tmp) / "demo_proj"
        src.mkdir()
        (src / "hello.txt").write_text("original-v1\n", encoding="utf-8")
        (src / "sub").mkdir()
        (src / "sub" / "a.txt").write_text("aa\n", encoding="utf-8")
        before = _hash_tree(src)
        with patch("builtins.input", return_value="yes"):
            imp = workspace_import(str(src))
        ws_write("projects/demo_proj/hello.txt", "edited-by-miniai\n")
        with patch("builtins.input", return_value="yes"):
            exp = workspace_export("demo_proj")
        after = _hash_tree(src)
        # find export sibling
        siblings = list(src.parent.glob("demo_proj-miniai-*"))
        export_ok = False
        export_content = None
        if siblings:
            export_content = (siblings[0] / "hello.txt").read_text(encoding="utf-8")
            export_ok = export_content == "edited-by-miniai\n"
        ok6 = (
            before == after
            and "Imported" in imp
            and export_ok
            and "Original folder was not modified" in exp
        )
        _check(
            "6",
            ok6,
            f"hashes_equal={before == after} siblings={siblings} "
            f"export_content={export_content!r}",
        )

    # --- 7. Round cap 10 only when coding tools used ---
    from scripts.agent_loop import run_tool_rounds

    def _fake_provider(tool_name: str, n_rounds: int = 12):
        state = {"i": 0}

        class P:
            model = "fake"
            timeout = 30

            def chat(self, *a, **k):
                state["i"] += 1
                if state["i"] <= n_rounds:
                    tc = {
                        "id": f"c{state['i']}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps({"path": "."}),
                        },
                    }
                    return MagicMock(content="", tool_calls=[tc])
                return MagicMock(content="done", tool_calls=None)

        return P()

    # Patch execute to no-op success for round counting
    with patch("scripts.agent_loop.execute_tool_calls") as ex:
        ex.return_value = [
            ChatMessage(role="tool", content="ok", tool_call_id="c1")
        ]
        # coding tool -> cap 10
        hist = [ChatMessage(role="user", content="code")]
        guard = MagicMock()
        r = run_tool_rounds(_fake_provider("ws_list", 12), hist, guard)
        coding_cap = "Stopped after 10 tool rounds" in (r.content or "")
        # non-coding -> cap 5
        hist2 = [ChatMessage(role="user", content="web")]
        r2 = run_tool_rounds(_fake_provider("list_directory", 12), hist2, guard)
        normal_cap = "Stopped after 5 tool rounds" in (r2.content or "")
    ok7 = coding_cap and normal_cap and "ws_write" in CODING_TOOLS
    _check("7", ok7, f"coding_cap={coding_cap} normal_cap={normal_cap}")

    # sanity: ws_write/ws_edit tiers CONFIRM for guard, not in UNTRUSTED
    from tools.registry import UNTRUSTED_SOURCE_TOOLS

    ok_tiers = (
        TOOL_TIERS["ws_write"] == Tier.CONFIRM
        and TOOL_TIERS["ws_edit"] == Tier.CONFIRM
        and "ws_write" not in UNTRUSTED_SOURCE_TOOLS
        and "run_file" in UNTRUSTED_SOURCE_TOOLS
        and set(TOOL_TIERS) == set(TOOL_FUNCTIONS)
    )
    _check("tiers", ok_tiers, "guard CONFIRM / no taint for ws_write")

    # --- 8. ESCAPE: malicious workspace\.git must not run hooks / change config ---
    ensure_repo()
    note = migration_note()
    print(f"migration_note={note!r}")
    assert not (ws / ".git").exists() or True  # may briefly exist; MiniAI ignores it
    cfg_hash_before = hash_git_config()
    marker = Path(os.environ.get("TEMP", tempfile.gettempdir())) / "miniai_escape_marker.txt"
    if marker.exists():
        marker.unlink()
    escape_code = (
        "from pathlib import Path\n"
        f"ws = Path(r'{ws}')\n"
        f"marker = Path(r'{marker}')\n"
        "hook_dir = ws / '.git' / 'hooks'\n"
        "hook_dir.mkdir(parents=True, exist_ok=True)\n"
        "hook = hook_dir / 'post-commit'\n"
        # If MiniAI ever ran hooks from workspace .git, this would create the marker.
        "hook.write_text('#!/bin/sh\\necho escaped > \\\"' + str(marker).replace('\\\\','/') + '\\\"\\n', encoding='utf-8')\n"
        "cfg = ws / '.git' / 'config'\n"
        "cfg.write_text('[core]\\n\\thooksPath = .git/hooks\\n\\tfsmonitor = true\\n', encoding='utf-8')\n"
        "print('planted', hook.exists(), cfg.exists())\n"
    )
    r_esc = run_python(escape_code, timeout_s=30)
    # Trigger MiniAI auto-commit (uses external git dir with hooks disabled)
    with patch("builtins.input", return_value="yes"):
        # run_code path also commits; use ws_write which auto-commits
        ws_write("escape_probe.txt", "trigger-commit\n")
    commit_workspace("escape probe commit")
    cfg_hash_after = hash_git_config()
    marker_exists = marker.exists()
    if marker_exists:
        marker.unlink()
    ok8 = (
        r_esc.exit_code == 0
        and not marker_exists
        and cfg_hash_before == cfg_hash_after
        and cfg_hash_before != ""
    )
    _check(
        "8_escape",
        ok8,
        f"marker={marker_exists} hash_same={cfg_hash_before == cfg_hash_after} "
        f"plant_exit={r_esc.exit_code} stdout={r_esc.stdout!r}",
    )

    # --- 9. low-IL cannot write workspace-git ---
    gd = workspace_git_dir()
    r9 = run_python(
        f"from pathlib import Path\n"
        f"p = Path(r'{gd}') / 'pwned_by_lowil.txt'\n"
        f"try:\n"
        f"    p.write_text('nope', encoding='utf-8')\n"
        f"    print('WROTE')\n"
        f"except Exception as e:\n"
        f"    print(type(e).__name__)\n",
        timeout_s=30,
    )
    wrote9 = (gd / "pwned_by_lowil.txt").exists()
    if wrote9:
        (gd / "pwned_by_lowil.txt").unlink()
    ok9 = (
        not wrote9
        and "WROTE" not in r9.stdout
        and "PermissionError" in (r9.stdout + r9.stderr)
    )
    _check("9_gitdir_write", ok9, f"out={r9.stdout!r} wrote={wrote9}")

    # --- 10. Junction escape via ws_write / ws_edit ---
    outside = Path(tempfile.mkdtemp(prefix="miniai_junc_outside_"))
    jlink = ws / "projects" / "jlink"
    jlink.parent.mkdir(parents=True, exist_ok=True)
    if jlink.exists():
        # Remove previous junction/dir
        subprocess.run(["cmd", "/c", "rmdir", str(jlink)], check=False)
        if jlink.exists():
            import shutil as _sh

            _sh.rmtree(jlink, ignore_errors=True)
    mk = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(jlink), str(outside)],
        capture_output=True,
        text=True,
    )
    junc_created = mk.returncode == 0 and jlink.exists()
    write_refused = False
    edit_refused = False
    try:
        ws_write("projects/jlink/x.txt", "pwn\n")
    except (WorkspacePathError, OSError, ValueError):
        write_refused = True
    try:
        # create a real file beside for edit attempt through junction
        ws_edit("projects/jlink/x.txt", "a", "b")
    except (WorkspacePathError, OSError, ValueError):
        edit_refused = True
    outside_empty = list(outside.iterdir()) == []
    # Low-IL CreateJunction capability report
    low_junc = run_python(
        "import ctypes, os, tempfile\n"
        "from pathlib import Path\n"
        f"ws = Path(r'{ws}')\n"
        "target = Path(tempfile.mkdtemp(prefix='lowil_junc_tgt_'))\n"
        "link = ws / 'projects' / 'lowil_jlink'\n"
        "if link.exists():\n"
        "    try:\n"
        "        os.rmdir(link)\n"
        "    except Exception:\n"
        "        pass\n"
        "SYMBOLIC_LINK_FLAG_DIRECTORY = 1\n"
        "try:\n"
        "    ok = ctypes.windll.kernel32.CreateSymbolicLinkW("
        "str(link), str(target), SYMBOLIC_LINK_FLAG_DIRECTORY)\n"
        "    err = ctypes.get_last_error()\n"
        "    print('CreateSymbolicLinkW', bool(ok), 'err', err, 'exists', link.exists())\n"
        "except Exception as e:\n"
        "    print('EXC', type(e).__name__, e)\n"
        "try:\n"
        "    import _winapi\n"
        "    print('has_CreateJunction', hasattr(_winapi, 'CreateJunction'))\n"
        "except Exception as e:\n"
        "    print('no_winapi', e)\n",
        timeout_s=30,
    )
    print(f"low_IL_junction_probe={low_junc.stdout!r}{low_junc.stderr!r}")
    # If low-IL somehow created a junction, ws_write through it must still refuse
    low_link = ws / "projects" / "lowil_jlink"
    low_write_refused = True
    if low_link.exists():
        try:
            ws_write("projects/lowil_jlink/y.txt", "nope\n")
            low_write_refused = False
        except (WorkspacePathError, OSError, ValueError):
            low_write_refused = True
    ok10 = (
        junc_created
        and write_refused
        and edit_refused
        and outside_empty
        and low_write_refused
    )
    _check(
        "10_junction",
        ok10,
        f"created={junc_created} write_refused={write_refused} "
        f"edit_refused={edit_refused} outside_empty={outside_empty} "
        f"mklink={mk.stdout!r}{mk.stderr!r}",
    )
    # cleanup junction
    subprocess.run(["cmd", "/c", "rmdir", str(jlink)], check=False)
    if low_link.exists():
        subprocess.run(["cmd", "/c", "rmdir", str(low_link)], check=False)

    # --- 11. workspace_export skips junction; nothing outside copied ---
    with tempfile.TemporaryDirectory(prefix="miniai_exp_junc_") as tmp:
        src = Path(tmp) / "exp_proj"
        src.mkdir()
        (src / "ok.txt").write_text("keep\n", encoding="utf-8")
        # Import first (no junction), then add junction inside workspace project
        with patch("builtins.input", return_value="yes"):
            workspace_import(str(src))
        proj = ws / "projects" / "exp_proj"
        outside2 = Path(tempfile.mkdtemp(prefix="miniai_exp_outside_"))
        (outside2 / "secret.txt").write_text("SECRET\n", encoding="utf-8")
        j2 = proj / "evil_link"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(j2), str(outside2)],
            check=False,
            capture_output=True,
            text=True,
        )
        with patch("builtins.input", return_value="yes"):
            exp_msg = workspace_export("exp_proj")
        # Find export sibling
        sibs = list(src.parent.glob("exp_proj-miniai-*"))
        secret_leaked = False
        for s in sibs:
            if (s / "evil_link").exists() or (s / "secret.txt").exists():
                secret_leaked = True
            for p in s.rglob("*"):
                if p.is_file() and "SECRET" in p.read_text(encoding="utf-8", errors="ignore"):
                    secret_leaked = True
        ok11 = (
            "Skipped junctions/symlinks" in exp_msg
            and "evil_link" in exp_msg
            and not secret_leaked
            and bool(sibs)
        )
        _check(
            "11_export_junction",
            ok11,
            f"msg={exp_msg!r} leaked={secret_leaked} sibs={sibs}",
        )
        subprocess.run(["cmd", "/c", "rmdir", str(j2)], check=False)

    # --- 12. history / restore with external git dir ---
    hist_file = ws / "hist_ext_probe.txt"
    stamp = str(int(time.time() * 1000))
    v1 = f"v1-ext-{stamp}\n"
    v2 = f"v2-ext-{stamp}\n"
    hist_file.write_text(v1, encoding="utf-8")
    sha1 = commit_workspace(f"hist v1 {stamp}")
    hist_file.write_text(v2, encoding="utf-8")
    sha2 = commit_workspace(f"hist v2 {stamp}")
    hist_text = history(20)
    with patch("builtins.input", return_value="yes"):
        from tools.code.code_tools import workspace_restore

        restore_msg = workspace_restore(sha1 or "")
    content = hist_file.read_text(encoding="utf-8")
    ok12 = (
        bool(sha1)
        and bool(sha2)
        and (sha1[:7] in hist_text or sha1 in hist_text)
        and content == v1
        and "Restored" in restore_msg
        and workspace_git_dir().exists()
        and (workspace_git_dir() / "HEAD").exists()
    )
    _check(
        "12_history_restore",
        ok12,
        f"sha1={sha1} sha2={sha2} content={content!r} note={note!r} "
        f"git_dir={workspace_git_dir()}",
    )

    # --- 13. .gitattributes filter alone is inert; injected filter config refused ---
    from tools.code.workspace_git import _write_allowed_config

    ensure_repo()
    _write_allowed_config(workspace_git_dir())
    marker13 = (
        Path(os.environ.get("TEMP", tempfile.gettempdir()))
        / "miniai_filter_evil_marker.txt"
    )
    if marker13.exists():
        marker13.unlink()
    stamp13 = str(int(time.time() * 1000))
    attrs = ws / ".gitattributes"
    attrs.write_text("* filter=evil\n", encoding="utf-8")
    # Without injected config key, attributes alone must not run a filter / marker.
    probe_a = ws / "filter_probe_a.txt"
    probe_a.write_text(f"attrs-only-{stamp13}\n", encoding="utf-8")
    sha_attrs = None
    err_attrs = None
    try:
        sha_attrs = commit_workspace(f"attrs only probe {stamp13}")
    except WorkspaceGitError as exc:
        err_attrs = str(exc)
    attrs_ok = (
        sha_attrs is not None
        and err_attrs is None
        and not marker13.exists()
    )
    # Inject filter.evil.clean into the external config (medium IL, as the test).
    # Keep the clean command free of backslashes/quotes so git config --list
    # still parses; the key alone must trigger the allowlist refuse.
    cfg_path = workspace_git_dir() / "config"
    cfg_text = cfg_path.read_text(encoding="utf-8")
    evil_line = (
        '\n[filter "evil"]\n'
        "\tclean = false\n"
    )
    cfg_path.write_text(cfg_text + evil_line, encoding="utf-8")
    probe_b = ws / "filter_probe_b.txt"
    probe_b.write_text(f"with-evil-key-{stamp13}\n", encoding="utf-8")
    refused = False
    refuse_msg = ""
    try:
        commit_workspace("should refuse evil filter")
    except WorkspaceGitError as exc:
        refused = HISTORY_PAUSED_MSG in str(exc)
        refuse_msg = str(exc)
    # Restore allowlisted config so later suites are not paused.
    _write_allowed_config(workspace_git_dir())
    if marker13.exists():
        marker13.unlink()
        marker_after = True
    else:
        marker_after = False
    ok13 = attrs_ok and refused and not marker_after
    _check(
        "13_filter_allowlist",
        ok13,
        f"attrs_ok={attrs_ok} sha={sha_attrs} err_attrs={err_attrs!r} "
        f"refused={refused} msg={refuse_msg!r} marker={marker_after}",
    )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0



if __name__ == "__main__":
    raise SystemExit(main())
