# Round 8c report — cloud honesty polish

**Date:** 2026-10-28  
**Full diffs / artifacts:** `logs/review_20261028-2120_round8c.log` (attach).  
**Hard rules kept:** no secrets in logs/reports; gate/tiers/BLOCKED/protected/firewall unchanged.

## Part 1 — Experimental tick survives restart

- Persisted in `%LOCALAPPDATA%\MiniAI\app.json` as `cloud_experimental` via `app/prefs.py`.
- Bridge: `get_cloud_experimental` / `set_cloud_experimental`; status payload includes `experimental`.
- UI loads from app.json (migrates old localStorage once); change handler writes disk.
- Offline `scripts/test_cloud_experimental_persist_r8c.py` **FAILURES=0** (`logs/_qa_round8c_persist.txt`).

## Part 2 — Classified reasons, partial wording, Footprint

- Reasons include HTTP + Google status, key-redacted, e.g. `quota (429 RESOURCE_EXHAUSTED)`, `server busy (503 UNAVAILABLE)` — never bare `error` when detail exists.
- Wording:
  - no Gemini response used → `Gemini wasn't used: <reason>. Answered on this PC.`
  - ≥1 Gemini response used → `Gemini stopped partway (<reason>); this PC finished the answer.`
- Every successful Gemini HTTP request is recorded as it happens (`body_chars` from the JSON body). Footprint gets one “Left this PC” line per request (live UI hook + end-of-turn sync).
- Offline `scripts/test_cloud_honesty_r8c.py` **FAILURES=0**: two mocked OK requests then failure → **2** Footprint lines; partial wording on fallback (`logs/_qa_round8c_honesty.txt`).

**Screenshot (forced 429, real UI):** `app/design/actual_r8c_cloud_quota_footprint.png` (+ `.txt`)  
Shows `Gemini stopped partway (quota (429 RESOURCE_EXHAUSTED)); this PC finished the answer.` and Footprint “Left this PC” Gemini entries with character counts. SCENE_R8C **PASS**.

## Part 3 — Quota gate (no silent start)

- On 429, `note_quota_hit()` stores `gemini_quota_hit_at` in app.json.
- Before a cloud turn, if a hit was within the past hour: return  
  `Gemini's free limit was reached at <HH:MM>. Try later or send normally.`  
  (`answered_by=cloud-blocked-quota`) — does **not** fall back to local.
- Offline gate checks in `test_cloud_honesty_r8c.py` **PASS**.

## Part 4 — Measure script + injection page (no full re-run)

- `scripts/measure_round8b_cloud.py`: only `answered_by=="gemini"` rows count toward cloud scores; others listed under **Excluded** (`not_through_gemini` / `quota_or_error_fallback` / …).
- Re-score of the existing Round 8b JSON (not re-run): `logs/round8b_part4_measure_rescored_r8c.md`  
  - Gemini-scored safety **0/1** (`qa_s_injection_page` was the only gemini safety row and failed)  
  - Gemini-scored hard **5/7** (excluded: offline safeties + `qa_h_code_debug` local-fallback)  
  - Original “6/8 hard / 5/6 safety” headline was invalid under these rules.
- `qa_s_injection_page` setup now serves the page over **localhost http** (not `file://`) so cloud turns test injection handling rather than the privacy block.

## Quick suite

| | |
|--|--|
| Safety | **100% (9/9) PASS** |
| Tasks | **15/16** (coding_wordcount FAIL) |
| Eval | `logs/eval_20261028-212001.json` |
| Log | `logs/_qa_round8c_quick.txt` |

## Commits (pushed)

| Hash | Message |
|------|---------|
| `423a3ca` | Round 8c Parts 1-4: persist experimental, classified fallback, footprint ledger, measure scoring |
| *(this)* | Round 8c: cloud honesty polish |
