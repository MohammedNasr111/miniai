# Round 7 Report — MiniAI v2 UI (run log + footprint)

Design reference: `app/design/miniai_v2_concept.html`. Local fonts only (Bahnschrift, Segoe UI Variable Text, Cascadia Code). CSP / nonce / escape-first unchanged. `security/` and permission tiers untouched.

## Screenshots (actual vs concept)

| Scene | Actual | Concept alignment |
|-------|--------|-------------------|
| Empty new chat | `app/design/actual_v9_empty.png` | Three example chips (files / web / code); rail + machine panel |
| Move ticket pending | `app/design/actual_v9_ticket_pending.png` | Perforated ticket, amber border, “Move 5 files” / “Don't move” |
| After approve | `app/design/actual_v9_ticket_done.png` | Collapsed muted line + change + verify nodes |
| Web mid-stream | `app/design/actual_v9_web_stream.png` | Lilac dashed “out” nodes + streaming caret |
| Footprint open | `app/design/actual_v9_footprint.png` | Ledger sections + no-upload line + context gauge |
| Command palette | `app/design/actual_v9_palette.png` | Centred Ctrl+K palette |
| Narrow ~700 px | `app/design/actual_v9_narrow700.png` | Rail slide-over |
| Live model turn | `app/design/actual_v9_live_run.png` | Real agent run (Stop state) |

Capture: `scripts/capture_v9_ui.py` (real pywebview window + Lemonade model).

## Deliberate deviations

1. **No Google Fonts** — concept HTML loads Barlow / IBM Plex / JetBrains; production uses Windows 11 fonts only per task.
2. **Footprint always in third column ≥1100 px** — matches concept; below 1100 px it is a slide-over (Ctrl+. / header button).
3. **Ticket copy is derived from action + description** — gate still sends the same typed/yes-no payload; UI maps to plain-English buttons via `app.action_classes.ticket_copy` (no `paths` field from the gate).
4. **Tok/s** — estimated from streamed answer length (~4 chars/token) for the last stream; shown on the rail.
5. **Self-check “Run now”** — palette starts the safety quick suite in a background thread and refreshes the rail when finished (does not block the UI).

## Offline tests

`scripts/test_round7_ui.py`: **FAILURES=0**

- Every registered tool has an action class (fails if a new tool is unmapped).
- Footprint records left / read / changed / verified; deletes mention Recycle Bin; `assert_no_upload` always true with line “No files or memories were uploaded.”
- Ticket labels: Delete file / Keep it; Move N files / Don't move; never generic Approve / Deny.
- No middle-dot (`·`) characters in UI strings or `app/ui/{app.js,index.html,styles.css}`.

## Quick suite

Log: `logs/_qa_round7_quick.txt` / `logs/eval_20261026-072253.json`

- **Safety: PASS (9/9)**
- All quick abilities passed (coding, counting, desktop, files, knowledge, memory, safety, web).

## Commits

| Part | Hash | Message |
|------|------|---------|
| 1 | `8292a53` | App v2 UI Part 1: tokens and three-column shell |
| 2 | `38a2d34` | App v2 UI Part 2: runs and action-trace spine |
| 3 | `469d1b9` | App v2 UI Part 3: permission tickets in the action trace |
| 4 | `63cba51` | App v2 UI Part 4: footprint ledger persisted per chat |
| 5 | `d1d2c51` | App v2 UI Part 5: command palette Ctrl+K (concept reference) |
| 6 | `5144ddf` | App v2 UI Part 6: polish (focus rings, reduced motion, jump-to-latest) |
| 7 | `e3ca51a` | App v2 UI: run log, action trace, permission tickets, footprint ledger, command palette |

## Bottom line

The desktop UI is now a run log with a coloured action-trace spine, in-trace permission tickets, a per-chat footprint ledger, and a Ctrl+K command palette — matching the v2 concept closely while keeping approvals and safety on the existing backend.
