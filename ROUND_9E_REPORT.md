# Round 9E report — make the app *feel* fast

Date: 2026-10-30 / 2026-10-31. Model: Qwen3-30B-A3B-GGUF. Task: `tasks/ROUND_9E_FEEL_FAST.md`.

Full diffs / new files: `logs/review_*_round9e_*.log` where written; otherwise attach the part commits.

## Keep rule (Part 2)

| Gate | Result |
|---|---|
| Case (e) mean wall improves ≥ 25% | **FAIL** — clean measure **24.9%** (63.127 → 47.384 s); drafts 3/3 → 0/3 |
| Battery mean ≥ 15 | **FAIL** — mean **13.5** (13/20 + 14/20) |
| Safety 100% | **PASS** — quick Safety PASS (`logs/round9e_quick.json`) |

Feel-speed wins shipped anyway: no erased analytical draft; Thinking… UI; UTF-8; honest chip; bold listing names.

## Part 1 — UTF-8 streams

- `response.encoding = "utf-8"` before `iter_lines` / `json()` in Lemonade + Gemini.
- Offline: `scripts/test_round9e_utf8.py` FAILURES=0.
- Commit: `c05139e`

## Part 2 — think-first (no discarded drafts)

- `MINIAI_THINK_FIRST` (default **on**): analytical / `two_pass` with **no** tool result yet → first call thinking-on; never stream a draft that will be erased.
- Synthesis (tool result in current turn) unchanged.
- UI: `on_thinking_start` → “Thinking… N s” until first stream delta.
- Offline: `scripts/test_round9e_think_first.py` FAILURES=0.

### Case (e) before / after

Prompt: “In about 150 words, explain how a CPU cache works.” ×3 each. Primary clean pair after restore: `logs/round9e_case_e_off_r2.json` / `logs/round9e_case_e_on_r2.json` (summary `logs/round9e_case_e_summary.json`).

| Mode | Walls (s) | Mean | Draft discarded |
|---|---|---:|---|
| `THINK_FIRST=off` | 66.574, 61.178, 61.628 | **63.127** | True, True, True |
| `THINK_FIRST=on` | 49.879, 47.584, 44.690 | **47.384** | False, False, False |
| Improve | | **24.9%** | — |

Hand-test reference (architect): ~88 s with discard → ~47 s is ~46% wall cut, but the keep rule uses scripted off→on.

First *visible* token is later with think-first (~31 s mean) because nothing streams during thinking — by design.

### Battery ×2

`logs/round9e_battery.json`: **13/20** + **14/20** (mean **13.5**). Quick: Safety PASS, 16/16 (`logs/round9e_quick.json`).

Commit: `882d3b2`

## Part 3 — honest speed chip

- Probe / verdict tok/s = llama.cpp `timings.predicted_per_second` only (no wall-clock fallback); missing → `UNKNOWN`, not DEGRADED.
- “Running slowly” only after **two** consecutive DEGRADED checks; probe scheduled after warm-up finishes (not at busy app_start).
- Sidebar “Writing speed” from last local `llm_call` `predicted_per_second`; cloud → “—”.
- Offline: `scripts/test_round9e_speed_chip.py` FAILURES=0.
- Commit: `34849e3`

## Part 4 — listing guard normalisation

- `normalize_listing_name`: strip bold/italics anywhere, backticks/quotes, trailing size / em-dash / date; case-fold; collapse space.
- Claim extraction includes bold tokens (e.g. `**sci exama.pdf**`).
- Exact 30 Oct answer:
  `1. **CursorUserSetup-x64-3.19.13.exe** — 196 MB` …
  → **no** correction, **no** Removed note.
- Commit: `30fad95`

## Commit hashes

| Part | Hash |
|---|---|
| 1 UTF-8 | `c05139e` |
| 2 think-first + measure | `882d3b2` |
| 3 speed chip | `34849e3` |
| 4 listing normalise | `30fad95` |
| Report | *(this commit)* |

## Finish

- MiniAI restarted; `check_model_state` = OK; “Hi” answered (see finish notes in PROJECT_LOG / `logs/_qa_round9e_hi.txt`).
