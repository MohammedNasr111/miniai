"""Round 12 Part 3 — live phase transitions (offline, fake tools)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def test_phase_helper() -> None:
    from app.turn_phase import phase_from_turn

    p = phase_from_turn(warming=True)
    _check("warming", p["label"] == "Warming up…" and p["show_elapsed"] is True, repr(p))

    p = phase_from_turn(waiting=True)
    _check(
        "approval",
        p["label"] == "Waiting for your approval" and p["show_elapsed"] is False,
        repr(p),
    )

    p = phase_from_turn(checking=True)
    _check(
        "checking",
        p["label"] == "Checking the answer…" and p["show_elapsed"] is False,
        repr(p),
    )

    p = phase_from_turn(thinking=True)
    _check("thinking", p["label"] == "Thinking…" and p["show_elapsed"] is True, repr(p))

    p = phase_from_turn(writing=True)
    _check("writing", p["label"] == "Writing…" and p["show_elapsed"] is True, repr(p))

    steps = [
        {
            "tool": "list_directory",
            "name": "Listing a folder",
            "running": True,
            "args": {"path": r"C:\Users\james\Downloads"},
        }
    ]
    p = phase_from_turn(steps=steps)
    _check(
        "reading_path",
        p["label"].startswith("Reading ") and "Downloads" in p["label"] and p["show_elapsed"],
        repr(p),
    )


def test_fake_provider_tools_drive_phase() -> None:
    """Fake provider + fake tool steps → activity payload phases."""
    from app.turn_phase import phase_from_turn

    # Simulate a tiny turn: warm → tool → approval → thinking → writing → check
    sequence = []
    sequence.append(phase_from_turn(warming=True))
    sequence.append(
        phase_from_turn(
            steps=[
                {
                    "tool": "read_file",
                    "name": "Reading a file",
                    "running": True,
                    "args": {"path": r"C:\Users\james\Documents\notes.txt"},
                }
            ]
        )
    )
    sequence.append(phase_from_turn(waiting=True))
    sequence.append(phase_from_turn(thinking=True))
    sequence.append(phase_from_turn(writing=True))
    sequence.append(phase_from_turn(checking=True))

    kinds = [s["kind"] for s in sequence]
    _check(
        "sequence_kinds",
        kinds == ["warming", "tool", "approval", "thinking", "writing", "checking"],
        repr(kinds),
    )

    # Fake "provider" that only yields a plan; tools are applied as step rows.
    provider = MagicMock()
    provider.chat = MagicMock(return_value=MagicMock(content="done", tool_calls=None))
    fake_tools = [
        {"name": "list_directory", "args": {"path": r"C:\Users\james\Desktop"}},
        {"name": "create_folder", "args": {"path": r"C:\Users\james\Desktop\Inbox"}},
    ]
    tool_phases = []
    for t in fake_tools:
        tool_phases.append(
            phase_from_turn(
                steps=[
                    {
                        "tool": t["name"],
                        "name": t["name"],
                        "running": True,
                        "args": t["args"],
                    }
                ]
            )
        )
    _check("fake_tools_all_elapsed", all(p["show_elapsed"] for p in tool_phases))
    _check(
        "fake_tools_reading_labels",
        all(p["label"].startswith("Reading ") for p in tool_phases),
        repr([p["label"] for p in tool_phases]),
    )
    _check("fake_provider_callable", callable(provider.chat))


def test_js_hooks() -> None:
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    for token in (
        "function setLivePhase",
        "function paintPhaseElapsed",
        "Waiting for your approval",
        "Checking the answer…",
        "Thinking…",
        "Writing…",
        "Warming up…",
        "Took <b>",
    ):
        _check(f"js:{token}", token in js)


def main() -> None:
    test_phase_helper()
    test_fake_provider_tools_drive_phase()
    test_js_hooks()
    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
