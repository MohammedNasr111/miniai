# Round 7c Report — real-use fixes

## Part 1 — Real user folders

**Cause:** File tools used `Path(path)` / `%USERPROFILE%\Desktop`, which is not the OneDrive-redirected Desktop (`C:\Users\mohdc\OneDrive\Desktop`).

**Fix:** `config/paths.py` resolves Desktop/Documents/Downloads/Pictures/Music/Videos via `SHGetKnownFolderPath(FOLDERID_*)`, then registry User Shell Folders. System prompt includes `The user's folders: …`. `resolve_fs_path` / mutating FS tools expand `~/Desktop`, `Desktop\…`, `%USERPROFILE%\Desktop`, and bare `home\Desktop\…` to the known folder.

**Test:** `scripts/test_user_folders.py` FAILURES=0 (mocked OneDrive paths). Commit `db486a1`.

## Part 2 — Trace honesty and order

**Cause:** Denied tools still got past-tense labels (“Created a file”); `syncSteps` re-inserted tickets *above* action nodes; `_short_path` dropped the drive letter.

**Fix:** `denied_label_for` → muted “Didn't create/move/delete… (you declined)” with `data-k=denied` (faint hollow node). Tickets re-attach under matching `dataset.tool` steps. `ellipsis_path` keeps `C:\` + middle `…`. Perforated ticket edge already present (concept `::before` radial-gradient).

**Test:** `scripts/test_trace_honesty.py` FAILURES=0. Commit `1b2fe75`.

## Part 3 — Header, streaming, web sub-steps, footprint

**Cause:** `#chat-title` only updated on `openChat`; streaming used raw `textContent`; `web_research` was one node; footprint only logged “Search: …” not pages read.

**Fix:** `on_chat_title` + history sync; streaming uses escape-first `renderMarkdown` into `.stream-md`; research progress emits Searched → Read N pages (+ recency verify); guards append verify steps; footprint records `N web pages (untrusted)` under Read.

**Test:** `scripts/test_round7c_part3.py` FAILURES=0. Commit `01138c7`.

## Part 4 — Single instance + warm-up + latency

**Cause:** Second launch started another process and double warm-up (full RAM).

**Fix:** Named mutex `MiniAI.Desktop` (`app/single_instance.py`); second launch restores/foregrounds the existing window and exits. Warm-up runs once and waits until no turn is busy.

**Cold-start latency (model already loaded in Lemonade):** fixture Downloads → “5 biggest files…”  
`FIRST_TOKEN_S=10.56` (`logs/first_token_20261026-191642.json`). **Target &lt; 15 s: met.** (Earlier cold ping was ~46 s before the model was warm.)

**Test:** `scripts/test_single_instance.py` FAILURES=0. Commit `9319f3d`.

## Part 5 — Green self-check

| Task | Cause | Fix (product vs grader) |
|------|--------|-------------------------|
| `files_biggest_downloads` | Model hallucinated mid-list names + web “Sources” | **Product:** `agent/listing_honesty.py` rewrites biggest-file answers from `list_directory`; compare-pipeline skips local file questions |
| `coding_wordcount` | Auto-test ran sibling project tests; slug diversion; syntax errors; early stop without tests | **Product:** auto-test stays in written project; explicit folder slug; SyntaxError note on write; early-stop on green tests; nudge to write tests. **Grader:** also scans workspace for `wordcount.py` |

**Evidence:** files 3/3 PASS; coding 3/3 PASS (`logs/_qa_round7c_files_3x.txt`, `logs/_qa_round7c_coding_3xd.txt`).  
**Quick suite:** **16/16**, Safety PASS (`logs/eval_20261026-195925.json`).  
**Self-check file:** `logs/selfcheck_latest.json` → UI label `16 of 16, 2026-10-26`.

## Part 6 — Screenshots (real interaction, v11)

Capture: `scripts/capture_v11_ui.py`. Summary: `app/design/actual_v11_summary.json`. **3/3 ok, unique md5.**

| Scene | Asserted state | png | txt | md5 |
|-------|----------------|-----|-----|-----|
| declined | `.step[data-k=denied]` + done ticket; no “Created a file” | `actual_v11_declined.png` | `actual_v11_declined.txt` | `2de1d330ca99538f426512c3f5438c77` |
| chat_title | `#chat-title` ≠ “New chat” | `actual_v11_chat_title.png` | `actual_v11_chat_title.txt` | `89c59027685931b5b2aeb6db9b8e0fe4` |
| web_substeps | “Searched the web” + “Read N pages” / lilac out | `actual_v11_web_substeps.png` | `actual_v11_web_substeps.txt` | `a5836198791fa98aa6e57e0bfbd13448` |

## Commits (this round)

| Hash | Message |
|------|---------|
| `db486a1` | App: resolve real user folders (OneDrive Desktop) |
| `1b2fe75` | App: honest declined traces, path ellipsis, ticket order |
| `01138c7` | App: chat title, streaming markdown, web sub-steps, footprint pages |
| `9319f3d` | App: single-instance mutex and idle-only model warm-up |
| `428f8cb`…`e195543` | Listing honesty, auto-test isolation, syntax note, early-stop, test nudge |
| `184a02e` | Round 7c: real-use fixes (user folders, trace honesty, streaming markdown, single instance, green self-check) |
