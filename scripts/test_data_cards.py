"""Offline: data cards sort/N match the question; prompt sentence only with card."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILURES
    if ok:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def _entries() -> list[dict]:
    return [
        {
            "name": "small.txt",
            "type": "file",
            "size_bytes": 10,
            "size": "10 B",
            "modified": "01 Jan, 1:00 pm",
        },
        {
            "name": "mid.bin",
            "type": "file",
            "size_bytes": 5000,
            "size": "4.9 KB",
            "modified": "15 Jun, 3:00 pm",
        },
        {
            "name": "huge.iso",
            "type": "file",
            "size_bytes": 9_000_000,
            "size": "8.6 MB",
            "modified": "28 Oct, 11:04 pm",
        },
        {
            "name": "alpha",
            "type": "dir",
            "size_bytes": None,
            "size": None,
            "modified": "10 Mar, 9:00 am",
        },
        {
            "name": "zeta.doc",
            "type": "file",
            "size_bytes": 200,
            "size": "200 B",
            "modified": "20 Sep, 8:00 am",
        },
    ]


def main() -> int:
    from agent.data_cards import (
        CARD_PROMPT_SENTENCE,
        build_data_card,
        listing_card_shown_this_turn,
        note_listing_card_shown,
        reset_listing_card_turn,
        sort_mode_for_question,
    )
    from scripts.agent_loop import _history_for_model
    from llm.base import ChatMessage

    raw = json.dumps(_entries())

    card3 = build_data_card(
        "list_directory",
        raw,
        question="What are the 3 biggest files in Downloads?",
        args={"path": "C:\\Downloads"},
    )
    check("card_built", card3 is not None)
    assert card3 is not None
    check("sort_size", card3["sort"] == "size", str(card3.get("sort")))
    check("limit_3", card3["limit"] == 3 and card3["shown"] == 3, str(card3))
    names3 = [r["name"] for r in card3["rows"]]
    check(
        "order_biggest_3",
        names3 == ["huge.iso", "mid.bin", "zeta.doc"],
        str(names3),
    )
    check("show_all_flag", card3["show_all"] is True)
    check(
        "all_rows_len",
        card3["all_rows"] is not None and len(card3["all_rows"]) == 5,
        str(card3.get("total")),
    )

    card_def = build_data_card(
        "list_directory",
        raw,
        question="What files are in my Downloads folder?",
        args={"path": "C:\\Downloads"},
        default_n=20,
    )
    check("default_n_20", card_def is not None and card_def["limit"] == 20)
    check(
        "sort_name_default",
        card_def is not None and card_def["sort"] == "name",
        str(card_def and card_def.get("sort")),
    )
    if card_def:
        names_n = [r["name"] for r in card_def["rows"]]
        check(
            "name_order",
            names_n == sorted(names_n, key=str.lower),
            str(names_n),
        )

    check(
        "sort_mode_newest",
        sort_mode_for_question("Show the newest files") == "modified",
    )

    search_paths = [
        "C:\\a\\zeta.txt",
        "C:\\a\\mid.txt",
        "C:\\a\\alpha.txt",
        "C:\\a\\beta.txt",
        "C:\\a\\gamma.txt",
        "C:\\a\\delta.txt",
    ]
    sc = build_data_card(
        "search_files",
        json.dumps(search_paths),
        question="Find the 2 files named txt",
        args={"root": "C:\\a", "pattern": "txt"},
    )
    check("search_limit_2", sc is not None and sc["shown"] == 2, str(sc))
    check(
        "search_show_all",
        sc is not None and sc["show_all"] and sc["total"] == 6,
    )

    reset_listing_card_turn()
    check("flag_off", not listing_card_shown_this_turn())
    hist = [
        ChatMessage(role="system", content="You are MiniAI."),
        ChatMessage(role="user", content="list files"),
    ]
    out0 = _history_for_model(hist)
    check("no_sentence_without_card", out0 is hist or out0[0].content == hist[0].content)
    check(
        "no_card_sentence_absent",
        CARD_PROMPT_SENTENCE not in (out0[0].content or ""),
    )

    note_listing_card_shown()
    check("flag_on", listing_card_shown_this_turn())
    out1 = _history_for_model(hist)
    check("sentence_added", CARD_PROMPT_SENTENCE in (out1[0].content or ""))
    check(
        "original_system_untouched",
        CARD_PROMPT_SENTENCE not in (hist[0].content or ""),
    )
    check(
        "user_untouched",
        out1[1].content == hist[1].content,
    )

    reset_listing_card_turn()
    if FAILURES:
        print(f"\n{FAILURES} failure(s)")
        return 1
    print("\nAll data_cards tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
