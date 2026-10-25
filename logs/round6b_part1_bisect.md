# Round 6b Part 1 — production health + bisect

## Health (all `MINIAI_FEATURE_*` default off)

Quick suite (`logs/_qa_round6b_part1_quick.txt`): **Safety PASS**; coding_wordcount PASS; files_biggest_downloads PASS.

Guard ×3 (`logs/_qa_round6b_part1_guards.txt`):

| Task | R4 | Part1 (flags off) |
|------|----|-------------------|
| qa_m_organise | 3/3 | **1/3** (below) |
| qa_m_duplicates | 3/3 | **1/3** (below) |
| coding_wordcount | pass | 3/3 |
| files_biggest_downloads | pass | 3/3 |

## Bisect

Range: `0c66e0f` (Round 5 report, good) … `4a746db` (HEAD, bad).  
Test: `qa_m_organise` ×2, good if ≥1 pass.

**First bad commit (git bisect):** `966e0b9` — *Round 6 Part 5: pre-register keep/disable rule*  
Diff is only gating slug/early-stop behind `FEATURE_CODING_AUTO_TEST` plus report files — **not a causal organise change** (bisect noisy; organise is flaky).

## Real unflagged surface (architect hypothesis confirmed)

With flags off, Round-6 tools still appeared in `TOOL_SCHEMAS` / system prompt (`analyze_table`, `ws_find_project`) and the coding turn cap stayed 16 whenever coding tools were used. That is unflagged Round-6 surface area from Parts 1–2.

## Fix

- `active_tool_schemas()` omits `analyze_table` / `ws_find_project` when their feature flags are off; agent loop uses it for all model calls.
- System prompt R6 nudges gated on the same flags.
- Coding round budget 16 only when `FEATURE_CODING_AUTO_TEST` is on (else 12).

Organise remaining misses (wrong type-folder names / approval storms) are addressed in Part 2 (`move_files`).
