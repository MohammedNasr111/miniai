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
from tools.code.paths import workspace_dir  # noqa: E402
from tools.code.runner import run_python  # noqa: E402
from tools.code.workspace_git import history  # noqa: E402
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

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
