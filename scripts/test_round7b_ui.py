"""Round 7b offline checks: contrast defaults, composer label, empty footprint, self-check."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global FAILURES
    if cond:
        print(f"PASS: {name}")
    else:
        FAILURES += 1
        print(f"FAIL: {name} — {detail}")


def main() -> int:
    from config.log_rotation import read_selfcheck_summary

    html = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")

    # R3: no visible "Message" label in the composer form flow
    check(
        "composer_no_visible_message_label",
        'style="position:absolute;left:-9999px">Message</label>' not in html,
        "old off-screen label still present",
    )
    check(
        "composer_aria_label",
        'aria-label="Message"' in html,
        "textarea missing aria-label",
    )
    check(
        "composer_no_message_text_node",
        not re.search(r">Message<", html),
        "Message text still in HTML",
    )

    # R6: empty footprint copy present; no sample Windows update strings in UI sources
    check(
        "fp_empty_copy",
        "Nothing yet. Actions in this chat will be listed here." in html,
    )
    for bad in (
        "Windows 11 October update",
        "Search: Windows",
        "4 web pages",
    ):
        check(
            f"no_sample_{bad[:20]}",
            bad not in html and bad not in js,
            "sample footprint data in source",
        )

    # R2: body text token; default opacity rules
    check("token_text", "--text:#E4E8EE" in css.replace(" ", ""))
    check("body_uses_text", "color:var(--text)" in css)
    check(
        "scrim_default_hidden",
        ".scrim{display:none!important}" in css.replace(" ", "")
        or ".scrim{display:none !important}" in css
        or re.search(r"\.scrim\s*\{\s*display:\s*none\s*!important", css) is not None,
    )
    # No blanket opacity < 1 on containers (allow disabled / caret blink / reduced)
    bad_opacity = re.findall(
        r"\.(app|rail|log|foot|brand|mark)\s*\{[^}]*opacity\s*:\s*(0?\.\d+|0)\b",
        css,
    )
    check("no_dim_container_opacity", not bad_opacity, repr(bad_opacity))

    # R4: send uses SVG, not a lone ↑ that can mis-render
    check("send_svg", "<svg" in html and "↑" not in html.split("composer")[1][:800])

    # R5: self-check parsing
    with tempfile.TemporaryDirectory(prefix="miniai_sc_") as tmp:
        root = Path(tmp)
        check(
            "selfcheck_missing",
            read_selfcheck_summary(root).get("label") == "not run yet",
        )
        (root / "selfcheck_latest.json").write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(
                {"passed": 14, "total": 16, "failed": 2, "date": "2026-10-26"}
            ).encode("utf-8")
        )
        sc = read_selfcheck_summary(root)
        check("selfcheck_bom_ok", "2 failed" in sc.get("label", ""), repr(sc))
        check("selfcheck_bom_level", sc.get("level") == "danger")
        (root / "selfcheck_latest.json").write_text("{bad", encoding="utf-8")
        check(
            "selfcheck_corrupt",
            read_selfcheck_summary(root).get("label") == "unreadable",
        )
        (root / "selfcheck_latest.json").write_text(
            json.dumps(
                {"passed": 16, "total": 16, "failed": 0, "date": "2026-10-26"}
            ),
            encoding="utf-8",
        )
        sc_ok = read_selfcheck_summary(root)
        check(
            "selfcheck_ok_label",
            sc_ok.get("label") == "16 of 16, 2026-10-26",
            repr(sc_ok),
        )
        check("selfcheck_no_middot", "·" not in sc_ok.get("label", ""))

    # Live parse of project logs/selfcheck_latest.json must not be unreadable
    live = read_selfcheck_summary(ROOT / "logs")
    check(
        "live_selfcheck_not_unreadable",
        live.get("label") != "unreadable",
        repr(live),
    )

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
