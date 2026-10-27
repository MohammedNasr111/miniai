# Round 7f report — predictable quiet self-check; run-claim contradiction fix

**Date:** 2026-10-27  
**Full code diffs + new file:** `logs/review_20261027-2325_round7f.log` (attach that file; do not rely on tool output above).

## Part 1 — Predictable schedule

### Settings BEFORE (`Get-ScheduledTask … | Select -Expand Settings`)

```
MultipleInstances               : IgnoreNew
Compatibility                   : Win7
AllowDemandStart                : True
AllowHardTerminate              : True
DisallowStartIfOnBatteries      : False
Enabled                         : True
ExecutionTimeLimit              : PT72H
Hidden                          : False
RunOnlyIfIdle                   : True
StartWhenAvailable              : True
StopIfGoingOnBatteries          : False
WakeToRun                       : False
UseUnifiedSchedulingEngine      : True
```

(Also: LastRunTime 2026-10-27 22:00:22 — catch-up after missed 03:17.)

### Settings AFTER re-register

```
MultipleInstances               : IgnoreNew
Compatibility                   : Win7
AllowDemandStart                : True
AllowHardTerminate              : True
DisallowStartIfOnBatteries      : False
Enabled                         : True
ExecutionTimeLimit              : PT72H
Hidden                          : False
RunOnlyIfIdle                   : True
StartWhenAvailable              : False
StopIfGoingOnBatteries          : False
WakeToRun                       : False
UseUnifiedSchedulingEngine      : True
```

Trigger: daily `03:17` only (`DaysInterval=1`). Principal: current user, Limited, no elevation. Idle 10 min kept.  
Saved copies: `logs/review_20261027-round7f_sched_before.txt`, `logs/review_20261027-round7f_sched_after.txt`.

### Stale sidebar prompt (>3 days)

`read_selfcheck_summary` sets `stale` / `prompt_run` when the last **successful** run is older than 3 days. Label: `Self-check: last run <date>. Run now?`. The rail button is clickable only then; the app never auto-starts the suite. Palette “Run self-check now” still works anytime.

## Part 2 — Quiet self-check

### Nightly task list (`--suite nightly` = quick minus `needs_display: true`)

1. safety_git_escape  
2. safety_hostile_browser  
3. safety_injection_1  
4. safety_injection_2  
5. safety_protected_path  
6. safety_scripted_exfil  
7. safety_scripted_type_exfil  
8. safety_typed_taint  
9. counting_listdir  
10. files_biggest_downloads  
11. knowledge_sample_pdf  
12. memory_recall  
13. web_python_version  
14. coding_wordcount  

**Excluded (need a visible desktop window):** `desktop_read_insert`, `safety_password_field`.

### How it stays quiet

- Scheduled action: `powershell -WindowStyle Hidden … nightly_selfcheck.ps1`
- `scripts/run_selfcheck.py --mode nightly` uses `hidden_subprocess_kwargs()` (CREATE_NO_WINDOW) for the eval child
- One line appended to `logs/selfcheck_history.log` per run
- Palette / stale “Run now?” uses `--mode full` → **full quick suite** (16 tasks, visible windows OK)

## Part 3 — Contradictory coding answer (honesty)

### What the nightly log showed

Final answer: `Tests passed. Tests: 4 passed, 1 failing: fail test_punctuation — AssertionEr…`  
Grader: `pytest did not pass in workspace candidates` (`logs/eval_20261027-221049.json`).

### Root cause

1. `maybe_auto_run_tests` / `parse_pytest_summary` reports failures as **“failing”** (not “failed”).
2. Early-stop green check in `scripts/agent_loop.py` only looked for `"failed" not in low`, so a red summary still got the prefix **“Tests passed.”**
3. The early-stop path set `response.content` and **skipped** `check_run_claims`.
4. Separately, `check_run_claims` used `any(ok)` over the turn, so an earlier green run could excuse a later failure claim.

### Fix

- Early-stop treats `failing|failed|error|syntaxerror` as red.
- Early-stop answers still go through `check_run_claims`.
- `check_run_claims` uses the **latest** run’s exit status; strips a contradictory “Tests passed” prefix when the same answer reports failures; does not treat compact `Tests:` summaries as fabricated pytest dumps.

### Offline test

`python -m scripts.test_run_claim_check` → **FAILURES=0** (includes exact contradiction text + latest-vs-any_ok). Log: `logs/_qa_round7f_run_claim.txt`.

### Why `coding_wordcount` / `test_punctuation` failed that night

Model flakiness in the generated solution/tests (punctuation word-count assertion), not a grader bug. Grader unchanged. Tonight’s `coding_wordcount` ×3: **3/3 PASS** (`logs/eval_20261027-231458.json`, `logs/_qa_round7f_coding_x3.txt`).

## Part 4 — Quick suite

| | |
|--|--|
| Safety | **PASS** (9/9) |
| Tasks | **16/16** |
| Eval JSON | `logs/eval_20261027-232449.json` |
| Console log | `logs/_qa_round7f_quick.txt` |

## Files touched

**New:** `scripts/run_selfcheck.py`  
**Changed:** `scripts/register_nightly_selfcheck.ps1`, `scripts/nightly_selfcheck.ps1`, `scripts/agent_loop.py`, `agent/run_claim_check.py`, `scripts/test_run_claim_check.py`, `eval/run.py`, `eval/tasks/desktop_read_insert.yaml`, `eval/tasks/safety_password_field.yaml`, `config/log_rotation.py`, `app/webview_approver.py`, `app/ui/app.js`, `app/ui/index.html`, `app/ui/styles.css`

Full contents/diffs: `logs/review_20261027-2325_round7f.log`.
