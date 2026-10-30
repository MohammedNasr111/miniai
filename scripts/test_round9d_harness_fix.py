"""Round 9D Part 4 — offline checks for harness + protected-path coding hint."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILURES = 0


def _check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    status = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES += 1
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def test_yaml_approves_create_folder() -> None:
    text = (ROOT / "eval" / "tasks" / "qa_m_code_small.yaml").read_text(encoding="utf-8")
    _check(
        "qa_m_code_small maps create_folder yes",
        "create_folder:" in text and '"yes"' in text.split("create_folder:", 1)[1][:40],
    )
    _check(
        "qa_m_code_small maps create_file yes",
        "create_file:" in text and '"yes"' in text.split("create_file:", 1)[1][:40],
    )


def test_setup_pdf_wraps_index_approval() -> None:
    from eval import qa_fixtures

    src = inspect.getsource(qa_fixtures.setup_qa_pdf)
    _check(
        "setup_qa_pdf uses answer_by_action for index_documents",
        "answer_by_action" in src and "index_documents" in src,
        "missing wrap" if "answer_by_action" not in src else "",
    )


def test_create_folder_protected_hint() -> None:
    from security.protected_paths import PROJECT_ROOT, PROTECTED_MESSAGE, ProtectedPathError
    from tools.filesystem.fs_tools import create_folder

    rel = "function_checks_string_palindrome"
    # Ensure relative resolve lands under PROJECT_ROOT (cwd may vary).
    target = PROJECT_ROOT / rel
    try:
        create_folder(str(target))
        _check("create_folder protected raises", False, "no exception")
    except ProtectedPathError as exc:
        msg = str(exc)
        _check("create_folder keeps PROTECTED_MESSAGE", PROTECTED_MESSAGE in msg)
        _check("create_folder hints ws_write", "ws_write" in msg)
        _check(
            "create_folder says do not retry under project",
            "Do not retry" in msg or "isolated workspace" in msg,
        )
    except Exception as exc:
        _check("create_folder protected raises", False, f"{type(exc).__name__}: {exc}")


def test_create_folder_tool_schema_mentions_ws_write() -> None:
    from tools import registry

    schemas = registry.TOOL_SCHEMAS if hasattr(registry, "TOOL_SCHEMAS") else None
    if schemas is None:
        # Fall back to scanning TOOL_DEFINITIONS / similar.
        blob = ""
        for name in dir(registry):
            if "SCHEMA" in name.upper() or name.endswith("_TOOLS"):
                blob += str(getattr(registry, name))
        # Also read the create_folder entry from TOOLS list pattern.
        import tools.registry as reg

        text = Path(reg.__file__).read_text(encoding="utf-8")
        # Locate create_folder description block
        idx = text.find('"name": "create_folder"')
        chunk = text[idx : idx + 800] if idx >= 0 else ""
        _check("create_folder schema mentions ws_write", "ws_write" in chunk)
        return
    # If TOOL_SCHEMAS exists, search it
    found = False
    for s in schemas:
        fn = (s.get("function") or {}) if isinstance(s, dict) else {}
        if fn.get("name") == "create_folder":
            found = "ws_write" in (fn.get("description") or "")
            break
    _check("create_folder schema mentions ws_write", found)


def main() -> int:
    test_yaml_approves_create_folder()
    test_setup_pdf_wraps_index_approval()
    test_create_folder_protected_hint()
    test_create_folder_tool_schema_mentions_ws_write()
    print(f"FAILURES={FAILURES}")
    return 0 if FAILURES == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
