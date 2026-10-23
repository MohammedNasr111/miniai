"""Offline markdown renderer tests (nested lists + Windows-update answer)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES = 0

WINDOWS_UPDATE_ANSWER = """The latest Windows 11 updates (as of 2026) emphasize deeper AI integration and interface refinements. Key changes include:

1. **AI-Powered Features**:
   - **Copilot Voice**: Enables voice chat with Microsoft Copilot, allowing the AI to access your screen and perform actions upon request.
   - **AI in Settings**: A new "Agent" in Settings uses natural language to help manage configurations.
   - **Enhanced Narrator**: Provides detailed image descriptions for better accessibility.
   - **Task Manager Upgrades**: Monitors AI workloads and NPU (Neural Processing Unit) activity.

2. **User Interface Changes**:
   - The **Print Screen (PrtScn)** key now opens the Snipping Tool by default, enabling customizable screenshot captures. Users can revert to the old behavior via Settings.

3. **Copilot+ PCs**:
   - New devices feature NPUs capable of 40+ trillion operations per second, optimizing AI tasks and enhancing performance.

4. **Windows 11 2026 Update**:
   - Aggregates features from previous year's monthly updates, including improved sharing tools, enhanced security, and personalized experiences.

Note: The exact release date for these updates is unclear from the sources, and some details may vary by device or region. For precise information, check Microsoft's official [Windows 11 release notes](https://support.microsoft.com/en-us/windows) or the [Windows Experience Blog](https://blogs.windows.com/windowsexperience/).
"""


def _check(name: str, ok: bool, detail: str) -> None:
    global FAILURES
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES += 1


def main() -> int:
    # Prefer importing a Python mirror that must match app.js behaviour.
    # Keep the mirror next to this test; also verify app.js contains nested-list code.
    js = (PROJECT_ROOT / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    _check(
        "js_has_nested_stack",
        "stack.push" in js and "closeTo" in js,
        "app.js nested list helpers",
    )

    # Inline Python port of the JS renderer (must stay aligned with app.js).
    def escape_html(s: str) -> str:
        return (
            str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def inline(s: str) -> str:
        t = escape_html(s)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(^|[^*])\*([^*]+)\*", r"\1<em>\2</em>", t)

        def _link(m):
            label, url = m.group(1), m.group(2).strip()
            if re.match(r"^https?://", url, re.I):
                return (
                    f'<a class="md-link" href="{escape_html(url)}" '
                    f'rel="noopener noreferrer">{label}</a>'
                )
            return f"{label} ({escape_html(url)})"

        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, t)
        return t

    def render_markdown(src: str) -> str:
        lines = str(src or "").splitlines()
        out: list[str] = []
        stack: list[dict] = []

        def close_to(indent: int) -> None:
            while stack and stack[-1]["indent"] > indent:
                frame = stack.pop()
                if frame.get("openLi"):
                    out.append("</li>")
                out.append("</" + frame["type"] + ">")

        def close_all() -> None:
            while stack:
                frame = stack.pop()
                if frame.get("openLi"):
                    out.append("</li>")
                out.append("</" + frame["type"] + ">")

        for line in lines:
            m = re.match(r"^([ \t]*)([-*]|\d+\.)\s+(.*)$", line)
            if m:
                raw = m.group(1).replace("\t", "  ")
                level = len(raw) // 2
                marker = m.group(2)
                body = m.group(3)
                list_type = "ol" if re.match(r"^\d+\.$", marker) else "ul"
                close_to(level)
                top = stack[-1] if stack else None
                if not top or top["indent"] < level:
                    out.append("<" + list_type + ">")
                    stack.append({"type": list_type, "indent": level, "openLi": False})
                    top = stack[-1]
                elif top["indent"] == level and top["type"] != list_type:
                    if top.get("openLi"):
                        out.append("</li>")
                    out.append("</" + top["type"] + ">")
                    stack.pop()
                    out.append("<" + list_type + ">")
                    stack.append({"type": list_type, "indent": level, "openLi": False})
                    top = stack[-1]
                elif top["indent"] == level and top.get("openLi"):
                    out.append("</li>")
                    top["openLi"] = False
                out.append("<li>" + inline(body))
                stack[-1]["openLi"] = True
                continue
            if line.strip() == "":
                close_all()
                continue
            close_all()
            out.append("<p>" + inline(line) + "</p>")
        close_all()
        return "".join(out) or "<p></p>"

    nested = render_markdown(
        "1. **Heading**:\n   - sub one\n   - sub two\n2. Next\n"
    )
    _check("nested_ol_ul", "<ol>" in nested and nested.count("<ul>") >= 1, nested[:300])
    _check("nested_li_count", nested.count("<li>") >= 4, nested)
    _check("no_stray_dash_p", "<p>- " not in nested, nested)

    html = render_markdown(WINDOWS_UPDATE_ANSWER)
    _check("win_has_ol", "<ol>" in html, "ol present")
    _check("win_has_nested_ul", "<ul>" in html, "ul present")
    _check(
        "win_bold_heading",
        "<strong>AI-Powered Features</strong>" in html
        or "<strong>Copilot Voice</strong>" in html,
        html[html.find("AI") : html.find("AI") + 80] if "AI" in html else html[:120],
    )
    _check(
        "win_https_link",
        'href="https://support.microsoft.com/en-us/windows"' in html,
        "release notes link",
    )
    _check(
        "win_no_stray_dash_paragraph",
        "<p>- " not in html and "<p>–" not in html,
        "no stray dash lines",
    )
    # Escape still applied for raw tags
    esc = render_markdown("use <script>alert(1)</script>")
    _check("escape_tags", "<script>" not in esc and "&lt;script&gt;" in esc, esc)

    print(f"\nFAILURES={FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
