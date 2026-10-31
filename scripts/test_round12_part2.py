"""Round 12 Part 2 — Settings panel (offline)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def main() -> None:
    html = (PROJECT_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app" / "ui" / "styles.css").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")

    _check("html_gear", 'id="btn-settings"' in html)
    _check("html_settings_title", ">Settings<" in html)
    _check("html_section_this_pc", 'id="settings-this-pc"' in html)
    _check("html_section_gemini", 'id="settings-gemini"' in html)
    _check("html_section_planner", 'id="settings-planner"' in html)
    _check("html_settings_scroll", 'settings-scroll' in html)
    _check("html_gemini_key", 'id="gemini-key-input"' in html)
    _check("html_groq_key", 'id="groq-key-input"' in html)
    _check("html_gemini_remove", 'id="gemini-remove"' in html)
    _check("html_groq_test", 'id="groq-test"' in html)
    _check("html_groq_remove", 'id="groq-remove"' in html)
    _check("html_experimental", 'id="cloud-experimental"' in html)

    _check("css_settings_scroll", ".settings-scroll" in css)
    _check("css_max_height", "max-height" in css and "settings" in css)
    _check("css_gear", ".gear{" in css or ".gear{" in css.replace(" ", ""))

    _check("js_ctrl_comma", 'e.key === ","' in js)
    _check("js_openSettings", "function openSettings" in js)
    _check("js_fillSettingsThisPc", "function fillSettingsThisPc" in js)
    for label in ("Settings", "Gemini", "Groq", "Planner", "Cloud", "Keys"):
        _check(f"js_palette:{label}", f'label: "{label}"' in js)

    # Fuzzy match: typing groq should hit Settings aliases or Groq entry
    _check("js_aliases_groq", '"groq"' in js and "aliases" in js)

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
