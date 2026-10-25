"""Offline tests for move_files batch tool (Round 6b Part 2)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

from security.gate import Tier, reset_session  # noqa: E402
from security.protected_paths import PROJECT_ROOT as MINIAI_ROOT  # noqa: E402
from tools.filesystem.fs_tools import move_files  # noqa: E402
from tools.registry import TOOL_FUNCTIONS, TOOL_TIERS  # noqa: E402

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    reset_session()
    _check(
        "registry",
        TOOL_FUNCTIONS.get("move_files") is move_files
        and TOOL_TIERS.get("move_files") == Tier.CONFIRM
        and set(TOOL_TIERS) == set(TOOL_FUNCTIONS),
        "",
    )

    with tempfile.TemporaryDirectory(prefix="miniai_moves_") as tmp:
        root = Path(tmp).resolve()
        files = []
        for i in range(5):
            p = root / f"f{i}.txt"
            p.write_text(f"x{i}\n", encoding="utf-8")
            files.append(p)
        dest_dir = root / "txt"
        moves = [
            {"src": str(p), "dest": str(dest_dir / p.name)} for p in files
        ]

        prompts = []

        def _gate(**kwargs):  # type: ignore[no-untyped-def]
            prompts.append(kwargs.get("description") or "")
            return None

        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            out = move_files(moves)
        _check("one_prompt", len(prompts) == 1, f"n={len(prompts)}")
        _check(
            "desc_lists",
            prompts and "Move 5 file(s)" in prompts[0] and "f0.txt" in prompts[0],
            (prompts[0][:200] if prompts else ""),
        )
        _check(
            "all_moved",
            all(not p.exists() for p in files)
            and all((dest_dir / p.name).is_file() for p in files)
            and "5 succeeded" in out,
            out[:300],
        )

        # Truncate display after 30
        many_src = []
        many_moves = []
        for i in range(35):
            p = root / f"many{i}.dat"
            p.write_text("z\n", encoding="utf-8")
            many_src.append(p)
            many_moves.append(
                {"src": str(p), "dest": str(root / "batch" / p.name)}
            )
        prompts.clear()
        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            move_files(many_moves)
        _check(
            "truncate_30",
            prompts and "and 5 more" in prompts[0],
            (prompts[0][-120:] if prompts else ""),
        )

        # Validation failure → no prompt, no moves
        bad = root / "ok.txt"
        bad.write_text("ok\n", encoding="utf-8")
        prompts.clear()
        raised = False
        try:
            with patch(
                "tools.filesystem.fs_tools.check_permission", side_effect=_gate
            ):
                move_files(
                    [
                        {"src": str(bad), "dest": str(root / "out" / "ok.txt")},
                        {
                            "src": str(MINIAI_ROOT / "ARCHITECTURE.md"),
                            "dest": str(root / "stolen.md"),
                        },
                    ]
                )
        except Exception as exc:
            raised = True
            detail = str(exc)[:200]
        else:
            detail = "no raise"
        _check(
            "validate_before_prompt",
            raised and not prompts and bad.exists(),
            detail,
        )

        # Partial failure reporting (dest already exists for one)
        a = root / "pa.txt"
        b = root / "pb.txt"
        a.write_text("a\n", encoding="utf-8")
        b.write_text("b\n", encoding="utf-8")
        taken = root / "out2" / "pa.txt"
        taken.parent.mkdir(parents=True, exist_ok=True)
        taken.write_text("taken\n", encoding="utf-8")
        prompts.clear()
        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            # Validation catches existing dest before prompt
            blocked = False
            try:
                move_files(
                    [
                        {"src": str(a), "dest": str(taken)},
                        {
                            "src": str(b),
                            "dest": str(root / "out2" / "pb.txt"),
                        },
                    ]
                )
            except FileExistsError:
                blocked = True
        _check(
            "existing_dest_no_prompt",
            blocked and not prompts and a.exists() and b.exists(),
            "",
        )

        # Mid-batch failure: validate passes, then one dest appears
        c = root / "pc.txt"
        d = root / "pd.txt"
        c.write_text("c\n", encoding="utf-8")
        d.write_text("d\n", encoding="utf-8")
        dest_c = root / "out3" / "pc.txt"
        dest_d = root / "out3" / "pd.txt"
        prompts.clear()

        real_mkdir = Path.mkdir

        def _mkdir_hijack(self, *a, **k):  # type: ignore[no-untyped-def]
            # After first successful move of c, plant a conflict for d
            result = real_mkdir(self, *a, **k)
            return result

        with patch("tools.filesystem.fs_tools.check_permission", side_effect=_gate):
            # First call succeeds both; simulate partial by making second dest exist
            # after validation via executing then checking reporting path:
            # call with d dest free, but patch shutil.move to fail on second
            calls = {"n": 0}
            real_move = __import__("shutil").move

            def _move(src, dst):  # type: ignore[no-untyped-def]
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError("simulated fail")
                return real_move(src, dst)

            with patch("tools.filesystem.fs_tools.shutil.move", side_effect=_move):
                out2 = move_files(
                    [
                        {"src": str(c), "dest": str(dest_c)},
                        {"src": str(d), "dest": str(dest_d)},
                    ]
                )
        _check(
            "partial_report",
            "1 succeeded" in out2
            and "1 failed" in out2
            and "OK:" in out2
            and "FAIL:" in out2
            and dest_c.is_file()
            and d.exists(),
            out2,
        )

    # Action-claim backs move_files
    from agent import action_claim_check as acc

    move_tools = None
    for _label, _rx, tools in acc._CLAIM_SPECS:
        if "move_file" in tools:
            move_tools = tools
            break
    _check(
        "action_claim",
        move_tools is not None and "move_files" in move_tools,
        str(move_tools),
    )

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
