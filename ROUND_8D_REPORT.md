# Round 8d report — coding_wordcount regression, run heading, honest screenshot

**Date:** 2026-10-28  
**Full diffs:** `logs/review_20261028-2352_round8d.log` (attach).  
**Hard rules kept:** no secrets; gate/tiers/BLOCKED/protected/firewall unchanged.

## Part 1 — coding_wordcount regression (product fix, not grader-wrong)

### Cause (from agent logs `_qa_round8b_quick.txt` / `_qa_round8c_quick.txt`)

Round 8b’s `--rootdir`/PYTHONPATH change was **not** breaking import of `wordcount` — good code still passes under the new runner. The three-in-a-row fails were a **coding-loop recovery** regression:

1. Auto-test ran after the model wrote tests with a bad assertion (e.g. `"   Multiple   spaces   "` expected 3 words but `split()` yields 2; or `\t`/`\n` escape mismatches).
2. Failure summaries only said `AssertionError: assert 2 == 3` — no assert **source** line — so the model thrashed with **identical** `ws_edit` no-ops (product accepted them as “1 replacement”).
3. Eventually the model introduced a `SyntaxError` in `wordcount.py`; grader re-ran pytest and failed with “pytest did not pass in workspace candidates”.

So: **product fix** (recovery / honesty of test feedback). Grader was also aligned to the same cwd/rootdir/PYTHONPATH as `run_tests` so agent and grade stay consistent.

### Fixes

| Change | Why |
|--------|-----|
| `ws_edit` rejects `old == new` | Stops fake progress / noop thrashing |
| Skip auto-test after blocked / `SyntaxError` tool results | Don’t burn rounds re-collecting broken syntax |
| `parse_pytest_summary` uses FAILURES-block window + assert source line | Model sees `assert count_words("…") == 3` |
| Auto-test failure nudge | “Fix the failing assert… do not make no-op edits” |
| Early-stop scores only the `Tests:` clause | Paths can’t false-positive “error” |
| Print `[AUTO-TEST] …` to stdout | Visible in agent logs |
| Grader uses project cwd/`--rootdir` + `_pytest_import_roots` | Same as product `run_tests` |

### Verification

| Check | Result |
|-------|--------|
| `scripts/test_coding_loop_r6.py` | **FAILURES=0** (`logs/_qa_round8d_coding_loop.txt`) |
| `coding_wordcount` ×3 | **3/3 PASS** (`logs/_qa_round8d_coding_x3b.txt`, `logs/eval_20261028-233939.json`) |
| Quick suite | **16/16**, Safety **9/9 PASS** (`logs/_qa_round8d_quick.txt`, `logs/eval_20261028-235146.json`) |

## Part 2 — Run heading is the user’s request

### Cause

Bridge-driven `send_message` (capture / Python API) never called JS `startRun(userText)`. First `on_activity` hit `startRun("(working)")`.

### Fix

- Every `on_activity` payload includes `ask` (the user text).
- `syncSteps` starts / repairs the run heading from `payload.ask` (never `"(working)"`).
- Composer path still sets `lastUserAsk` before send.

Capture assert: ask == `Write a tiny hello webpage in the workspace.` and not `(working)`.

## Part 3 — Honest Footprint screenshot

### Cause

Prior capture clicked a non-existent `btn-footprint`, saved while `#fp-body` was closed, then the 8c report claimed Footprint Gemini lines the PNG did not show.

### Fix

`scripts/capture_round8c_fallback.py` now:

1. Opens Footprint via `#open-foot` + `.show-foot`.
2. **Asserts before save:** `#fp-body` visible and ≥1 `Sent to Google Gemini` line.
3. Asserts run heading is the user ask.

### What the image shows (only what is claimed)

Retake: `app/design/actual_r8c_cloud_quota_footprint.png` (+ `.txt`)

- Run heading: **Write a tiny hello webpage in the workspace.**
- Answer header: `Gemini stopped partway (quota (429 RESOURCE_EXHAUSTED)); this PC finished the answer.`
- Footprint panel **open** with **Left this PC 3** and three “Sent to Google Gemini …” lines (character counts).
- `FP_CHECK`: `fpVisible=True`, `gemLines=3`, `askOk=True`. SCENE_R8C **PASS** (`logs/_qa_round8d_capture.txt`).

## Commits (pushed)

| Hash | Message |
|------|---------|
| `61e30f5` | Round 8d: coding_wordcount regression, run heading, honest screenshot |
