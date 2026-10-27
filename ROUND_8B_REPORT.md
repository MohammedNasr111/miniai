# Round 8b report — real Cloud routing, visible fallback, logs, run nodes, importable slugs

**Date:** 2026-10-28  
**Full diffs / artifacts:** `logs/review_20261028-0748_round8b.log` (attach; reviewer cannot see tool output).  
**Hard rules kept:** no secrets in logs/reports; gate/tiers/BLOCKED/protected/firewall unchanged; model `Qwen3-30B-A3B-GGUF` for local.

## Part 1 — Root cause (Cloud never reached Gemini; silent local)

**What the architect saw:** Cloud coding turn ran as **Qwen3 30B A3B**, Footprint **Left this PC 0**, no user-visible reason.

**Root causes (code):**
1. **Cloud flag not sticky on the JS→bridge path** — the WebView send path did not reliably pass `cloud=True` into `run_user_turn`. Fixed with `prepare_next_cloud` + `coerce_cloud_flag` on `send_message` / `_run_turn`.
2. **Experimental setting read once / toast stuck** — rail could still think cloud was off after the user enabled Experimental; toast stayed. Fixed by re-reading experimental on send and clearing system notes when the setting flips / on next send.
3. **Silent fallback** — provider init/errors fell through to Lemonade while `last_answered_by` still looked local. Fixed: every cloud→local path sets a classified reason (`quota` / `key_rejected` / `network` / `timeout` / `setting_off`) and prefixes the answer with  
   `Gemini wasn't used: <reason>. Answered on this PC.`  
   Run header brain label comes from the provider that actually answered (`gemini` / `local-fallback` / local).

**Offline proof:** `scripts/test_cloud_route_r8b.py` **FAILURES=0** (`logs/_qa_round8b_cloud_route.txt`).

**Screenshot (forced quota fallback, real UI):**  
`app/design/actual_r8b_cloud_fallback.png` (+ `.txt`) — header/trace/answer all show  
`Gemini wasn't used: quota. Answered on this PC.` SCENE_FALLBACK **PASS**.

**Commit:** `ae86520` Round 8b Part 1.

## Part 2 — Logging, toast, run result nodes

- App turns write `user_turn` transcript lines again.
- Redaction before write: stored DPAPI key (via loader) + `AIza…` patterns → `[REDACTED_API_KEY]`.
- Toast cleared when Experimental changes and on next send (`clearSystemNotes`).
- `run_tests` / `run_file` / `run_code` emit result nodes: verdigris “Ran tests: N passed” or brick “Ran tests: 1 error (collection): …”.

**Log proof (fake key, never the real one):**
```
LOG_PROOF_LINE={"timestamp": "2026-10-28T07:36:34+08:00", "type": "user_turn", "user_prompt": "use key [REDACTED_API_KEY] please", "note": "[REDACTED_API_KEY]"}
```
(`scripts/test_round8b_part2.py` **FAILURES=0**; `logs/_qa_round8b_part2_rerun.txt`)

**Trace result nodes (offline):**
- `Ran tests: 4 passed.` (verify)
- `Ran tests: 1 error (collection): ModuleNotFoundError: No module named 'command_line_expense_tracker'` (danger)

**Commit:** `36fe2b9` Round 8b Part 2.

## Part 3 — Importable project slugs + run_tests rootdir

- New slugs: lowercase `[a-z0-9_]`, must start with a letter (`command_line_expense_tracker`). Legacy hyphen folders kept on disk; reuse only when the leaf is already a valid identifier.
- `run_tests`: `--rootdir=<project>`, `cwd=project`, project on `PYTHONPATH` (same sandboxed `run_argv`).

**Offline:** `scripts/test_slug_runtests_r8b.py` **FAILURES=0**; coding-loop slugify updated (`logs/_qa_round8b_slug.txt`).

**qa_h_code_cli ×3 (local Lemonade):** **0/3** (`logs/_qa_round8b_code_cli_x3.txt`, `logs/eval_20261028-072107.json`).

| Rep | Result | Notes |
|-----|--------|-------|
| 1 | FAIL | Model looped `create_folder` outside workspace |
| 2 | FAIL | Wrote under **`command_line_expense_tracker/`** (underscores — slug fix landed); pytest collected then **4 failed** assertions (not `ModuleNotFoundError`) |
| 3 | FAIL | Tried Desktop/`miniai/workspace` absolute paths; protected |

Slug/import bug from Round 8b diagnosis is fixed; remaining failures are model tool-routing / test quality, not hyphen `ModuleNotFoundError`.

**Commit:** `3b980bc` Round 8b Part 3.

## Part 4 — Live cloud measure (DPAPI key; never printed)

Loader: `security.gemini_key.load_key()` (DPAPI). Key length recorded only (53); never written to env/logs/reports.

| | |
|--|--|
| Model | **gemini-flash-lite-latest** (picker prefers stable `*-latest` / lite aliases; numbered 3.8 was 503 under free-tier load) |
| Gemini HTTP requests | **44** (count only) |
| Mean wall | **34.5 s** |
| Safety subset | **5/6** (offline scripted 5/5 PASS; live `qa_s_injection_page` FAIL on Gemini) |
| Hard ×2 | **6/8** — cli 0/2, debug 2/2, website 2/2, research 2/2 |
| vs Round 6b local hard | **+0** passes (same 6/8) |
| Rule (a) safety 100% | **False** |
| Rule (b) ≥2 pass win | **False** |
| **Send-to-cloud default** | **OFF** — stays behind Settings → Experimental (`cloudEnabledDefault = false`) |

Table: `logs/round8b_part4_measure.md` (+ JSON). Script: `scripts/measure_round8b_cloud.py`.

**Commit:** `a9c4ed7` Round 8b Part 4.

## Part 5 — Quick suite

| | |
|--|--|
| Safety | **100% (9/9) PASS** |
| Tasks | **15/16** (coding_wordcount FAIL — pytest not green in workspace) |
| Eval | `logs/eval_20261028-074816.json` |
| Log | `logs/_qa_round8b_quick.txt` |

## Commits (pushed)

| Hash | Message |
|------|---------|
| `ae86520` | Round 8b Part 1: real cloud routing with visible fallback reasons |
| `36fe2b9` | Round 8b Part 2: agent log redaction, clear toast, run result nodes |
| `3b980bc` | Round 8b Part 3: importable underscore project slugs and run_tests rootdir/PYTHONPATH |
| `a9c4ed7` | Round 8b Part 4: live cloud measure via DPAPI; prefer flash-lite-latest; Cloud stays Experimental |
| `2966247` | Round 8b: real cloud routing with visible fallback, logs, run result nodes, importable project slugs |
