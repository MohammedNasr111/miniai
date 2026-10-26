# Round 7b Report — UI verify

## R1 — Staged v9 screenshots (architect)

**Cause:** `scripts/capture_v9_ui.py` injected staged DOM via `window.__v9Scene`. Several PNGs shared md5 `bf2e785b…` and showed the empty chat. Staged shots are not proof.

**Fix:** Replaced with `scripts/capture_v10_ui.py`: real `bridge.send_message`, real `move_files` ticket (clicked “Move 3 files”), DOM asserts before each capture, visible text saved to `.txt`, unique md5 check. No scene injection.

## R2 — Dim / low contrast

**Cause:** `.app.show-foot .scrim` / `.show-rail .scrim` lived **outside** the ≤1100px media query, so toggling Footprint on a wide window painted a 55% dark overlay over the whole UI. Brand/`--text` looked greyed.

**Fix:** Scrim only inside `@media (max-width:1100px)`. Default `.scrim{display:none!important}`. Explicit `color:var(--text)` / `opacity:1` on body, brand, mark, shell.

## R3 — “Message” in the composer

**Cause:** `<label style="position:absolute;left:-9999px">Message</label>` still participated in WebView2 layout and was visible beside the placeholder.

**Fix:** Removed the label; `aria-label="Message"` on the textarea. Offline test asserts no `label[for=composer]` and no `>Message<` text node.

## R4 — Narrow composer wrap + stray “[”

**Cause:** Long placeholder wrapped at ~720px; Send used a Unicode `↑` that could mis-render.

**Fix:** Placeholder shortened to `Ask MiniAI…` with ellipsis CSS; Send is an SVG arrow (Stop uses CSS `■` via `.is-stop`).

## R5 — Self-check “unreadable”

**Cause:** `logs/selfcheck_latest.json` is UTF-8 **with BOM** (PowerShell). `json.loads(..., encoding="utf-8")` raised; label became “unreadable”.

**Fix:** `read_selfcheck_summary` uses `utf-8-sig`; missing → `not run yet`; corrupt → `unreadable`; OK → `16 of 16, YYYY-MM-DD` (no middle dots). Live file now parses as `2 failed, 2026-10-26`.

## R6 — Sample footprint on a new chat

**Cause:** Capture inject left sample ledger entries; empty new chat still showed ledger chrome with zeros.

**Fix:** Empty state copy “Nothing yet. Actions in this chat will be listed here.”; `#fp-body` hidden until real counts > 0; `clearFootprint()` on boot / new chat. No sample strings in UI sources.

## R7 — Part 0 `memory_recall`

No separate Round 7 Part 0 commit existed. Evidence:

| Run | Result |
|-----|--------|
| Round 6b quick (`ROUND_6B_REPORT`) | **FAIL** `memory_recall` (baseline drop) |
| Round 7 quick (`logs/eval_20261026-072253.json`) | **PASS** `memory_recall` 13.7s |

**Verdict:** Flaky previously; **passing** on the Round 7 quick battery. Not a Round 7b code change.

---

## Part 2 — Start menu shortcut

Created `%APPDATA%\Microsoft\Windows\Start Menu\Programs\MiniAI.lnk` (and refreshed Desktop) via `scripts/make_shortcut.py`: same `pythonw.exe -m app`, icon, working directory, `AppUserModel.ID=MiniAI.Desktop`. Per-user, no elevation.

---

## Part 3 — Real screenshots (v10)

Capture: `scripts/capture_v10_ui.py`. Summary: `app/design/actual_v10_summary.json`. All **7/7** asserted; **unique md5=True**.

| Scene | Asserted state | png | txt | md5 |
|-------|----------------|-----|-----|-----|
| empty | `.empty`, no ticket, fp empty visible, no composer label | `actual_v10_empty.png` | `actual_v10_empty.txt` | `97fde3bee8578874983f2adccd57946b` |
| ticket_pending | `.ticket:not(.done)` + primary “Move 3 files” | `actual_v10_ticket_pending.png` | `actual_v10_ticket_pending.txt` | `679d0fdd34f6ac8328da8748c14e95a3` |
| ticket_done | `.ticket.done` + change/verify step | `actual_v10_ticket_done.png` | `actual_v10_ticket_done.txt` | `c40bf2753eaad80786f5f12a7f73c784` |
| web_stream | `.step[data-k=out]` (lilac) | `actual_v10_web_stream.png` | `actual_v10_web_stream.txt` | `a7e476122db6bd89915fea7df48ca9d5` |
| footprint | `#fp-body` shown, no sample Windows-11 string | `actual_v10_footprint.png` | `actual_v10_footprint.txt` | `e9ed28e90021bd5b271cbaf1d0351b80` |
| palette | `#palette` not hidden (Ctrl+K) | `actual_v10_palette.png` | `actual_v10_palette.txt` | `ae137543c60c31e2f061a8c7b689d804` |
| narrow640 | `#open-rail` displayed at 640px | `actual_v10_narrow640.png` | `actual_v10_narrow640.txt` | `70dc967563ad0257a9a80e33644701d9` |

---

## Offline tests

- `scripts/test_round7b_ui.py`: **FAILURES=0**
- `scripts/test_log_rotation.py`: **ALL PASS** (BOM / missing / corrupt self-check)

## Quick suite

- Stamp: `20261026-182756`
- JSON: `logs/eval_20261026-182756.json`
- Report: `eval/last_report.md`
- **Safety: 9/9 = 100% (PASS)**
- Overall tasks: 14/16 passed
- Ability fails (not safety): `files_biggest_downloads`, `coding_wordcount`
- Baseline drops: coding 0% < baseline 100%
- `memory_recall`: **PASS** (12.33s, fact_in_answer=True)

## Commits

| Part | Hash | Message |
|------|------|---------|
| 1 | `2a8504f` | App v2 UI fixes: contrast, composer label, narrow composer, self-check, empty footprint |
| 2 | `ddab608` | App: Start menu shortcut |
| 3 | `436e946` | UI proof: real-interaction screenshots v10 |
| 4 | `PENDING` | Round 7b report |
