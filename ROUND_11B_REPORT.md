# Round 11B report — Groq measure + harness fixes

Date: 2026-10-31. Task: `tasks/ROUND_11B_GROQ_AND_HARNESS.md`.

Full code / diffs / this report text: `logs/review_20261101-0038_round11b_report.log` (git-ignored; attach that file for review).

## Decisions (summary)

| Change | Decision | Why |
|---|---|---|
| Eval user-folder redirect | **kept** | Live evals must not write real Desktop/Documents |
| Organise harness approvals | **kept** | Was denying `create_folder`; after fix 2/3 |
| `FEATURE_ANALYZE_TABLE` | **Off** (unchanged) | Multistep 0/3 → 0/3; keep needs ≥+2/3 |
| Planner = Groq | **Off** (unchanged) | Targets 3/9 < off+3; guards 6/9 < off−1 |

---

## Part 1 — evals stay out of real user folders

Commit: `66f6b1c`

`config/paths.py` adds `install_eval_user_folders` / `set_eval_user_folders` / `real_user_folders`. `eval/run.py` installs the override per task and clears it in `finally`.

Offline+live: `scripts/test_round11b_part1.py` **FAILURES=0** — `qa_m_code_small` added **no** new names on the real Desktop.

### Desktop leftovers (listed only; not deleted)

| Name | Created |
|---|---|
| `function_checks_string_palindrome` | 2026-10-31 01:38:16 |

Also present on Desktop (not eval leftovers from this round): `miniai`, `MiniAI.lnk`, `miniai.zip`.

---

## Part 2 — `qa_m_organise` diagnosis and harness fix

Commit: `74fcc9c`

### Diagnosis ×2 (planner off)

Log: `logs/round11b_organise_diag.json` / `logs/_qa_round11b_organise_diag.txt`  
Score: **0/2**

Every `create_folder` approval was answered **no** (YAML lacked `create_folder`; default deny):

```
[TOOL CALL] create_folder({'path': '…\\Documents'})
[PERMISSION REQUIRED - CONFIRM]
Action: create_folder
[INPUT] action='create_folder' prompt='Allow? [yes/no]: ' -> 'no'
[TOOL RESULT] Denied by user: User denied: create_folder. Do not retry this call.
```

(Same pattern for Images / Executables / Other / PDFs on both runs.)

Final answers (both runs):

> You declined, so nothing was changed. Please allow the creation of subfolders to proceed with organizing the files by type.

### Fix

- `eval/tasks/qa_m_organise.yaml`: approve `create_folder` / moves; do **not** approve `delete_file`.
- Grader approval budget `nfiles+2` → `nfiles+6` (type-folder confirms) in `eval/qa_fixtures.py`.

### Re-run ×3 (planner off)

Log: `logs/round11b_organise_x3.json`  
Score: **2/3** (one fail `bad_folder:report.pdf->other`).

---

## Part 3 — `qa_h_multistep` + `analyze_table`

Commit: `08c1037`

### Failing total (quoted)

True total revenue = **1240** (= 100+250+180+90+400+220).

Off ×3 wrote correct best/worst (May $400 / April $90) but **omitted any total**. Example `write_file` content from `logs/_qa_round11b_multistep_off.txt`:

```
# Summary of Revenue by Month

## Best Month
- **Month**: May
- **Revenue**: $400

## Worst Month
- **Month**: April
- **Revenue**: $90
```

Run 3 listed monthly figures that sum to 1240 but still wrote **no** “total” line — grader `ok_total=False`.

### Scores

| Mode | Pass | Notes | Log |
|---|---:|---|---|
| ANALYZE_TABLE **off** | **0/3** | `ok_best`/`ok_worst` True; `ok_total` False | `logs/round11b_multistep_off.json` |
| ANALYZE_TABLE **on** | **0/3** | timeouts / wrong summary; best/worst also false | `logs/round11b_multistep_on.json` |

### Keep rule

Need ≥ +2/3 then battery ×2 mean ≥ 14.5 and safety 100%.  
On did not improve (0/3 → 0/3). **`FEATURE_ANALYZE_TABLE` stays Off.**

---

## Part 4 — Groq planner, measured properly

### Real secrets pointer

`security/groq_key.secrets_dir()` resolves via `config.paths.real_local_appdata()` so a redirected eval `LOCALAPPDATA` still sees the DPAPI file. Tests set `MINIAI_GROQ_SECRETS_DIR` to a temp folder.

Verify (`scripts/test_round11b_part4_secrets.py`): **FAILURES=0**

```
PASS: has_key_True
PASS: test_connected - status='Test OK'
connected
```

(Key length checked only; value never printed/logged.)

Offline regression: `scripts/test_round11_part0.py` **FAILURES=0**.

### Scoreboard (targets+guards ×3)

Control (off, after organise harness fix): `logs/round11b_off_targets.json`  
Groq: `logs/round11b_groq_targets.json`

| Mode | Targets | Guards | Mean wall (targets) |
|---|---:|---:|---:|
| **off** | **1/9** | **8/9** | **139.524 s** |
| **groq** | **3/9** | **6/9** | **171.583 s** |

Per-task passes:

| Task | off | groq |
|---|---:|---:|
| qa_h_code_cli | 0/3 | 0/3 |
| qa_h_multistep | 0/3 | 0/3 |
| qa_m_organise | 1/3 | **3/3** |
| qa_h_code_debug | 2/3 | 2/3 |
| qa_h_code_website | 3/3 | 1/3 |
| qa_m_code_small | 3/3 | 3/3 |

Two groq guard failures had `wall_s=0.0` with Lemonade load timeout (`Qwen3-30B-A3B-GGUF failed to load … Read timed out`).

### Keep rule

| Gate | Need | Groq | Met? |
|---|---|---|---|
| Targets ≥ off+3 | ≥ **4**/9 | 3/9 | **no** |
| Guards ≥ off−1 | ≥ **7**/9 | 6/9 | **no** |
| Wall ≤ 1.5×off | ≤ **209.286 s** | 171.583 s | yes |
| Battery ×2 / safety | — | not run | — |

**No mode kept. Default Planner = Off.**

### Groq requests / tokens / payload safety

Log: `logs/round11b_groq_requests.jsonl` (16 lines)  
Sample: `logs/round11b_groq_payload_sample.json`

| Metric | Value |
|---|---|
| HTTP requests | **16** |
| Host | `api.groq.com` only |
| `tool_count` | **0** on every request |
| `body_chars` sum | **18930** |
| Est. tokens (body/4) | **≈4732** (usage tokens were attached after `_note_sent` on this run; fixed afterward so future logs include `tokens`) |

Quoted sample payload (user text shortened; no key):

```json
{
  "model": "openai/gpt-oss-120b",
  "keys": ["messages", "model"],
  "n_messages": 2,
  "has_tools": false,
  "user_text_short": "User request:\nBuild a command-line expense tracker in Python: add an expense with amount, category and date; list expenses; show totals per category; store data in SQLite; include …",
  "system_head": "You are MiniAI's planner. Write a short JSON plan only — no tools, no prose outside JSON. Schema: {\"steps\":[{\"step\":\"...…"
}
```

Payload keys are only `messages` + `model` — no `tools`, no file bodies, no memory.

---

## Commits

| Part | Hash | Message |
|---|---|---|
| 1 | `66f6b1c` | Round 11B Part 1 — redirect eval user folders off real Desktop |
| 2 | `74fcc9c` | Round 11B Part 2 — fix organise harness approvals + grader budget |
| 3 | `08c1037` | Round 11B Part 3 — measure analyze_table on multistep; leave Off |
| 4 | `e6a06ef` | Round 11B Part 4 — Groq real-secrets path + measure; leave Off |
| Report | *(this commit)* | Round 11B — report + restart |

## Restart / smoke

- App restarted via `pythonw -m app`.
- `check_model_state` = **OK** (tok/s=12.244 ≥ 11.98). Log: `logs/model_state_20261031-163701.json` / `logs/_qa_round11b_model_state_final.txt`.
- Hi → `Hello! How can I assist you today?` (`logs/_qa_round11b_hi.txt`).

## Log index

- Part 1: `logs/_qa_round11b_part1.txt`
- Part 2 diag/x3: `logs/round11b_organise_diag.json`, `logs/round11b_organise_x3.json`
- Part 3: `logs/round11b_multistep_off.json`, `logs/round11b_multistep_on.json`
- Part 4 off/groq: `logs/round11b_off_targets.json`, `logs/round11b_groq_targets.json`
- Groq traffic: `logs/round11b_groq_requests.jsonl`, `logs/round11b_groq_payload_sample.json`
- Secrets verify: `logs/_qa_round11b_part4_secrets.txt`
- Hi / model_state: `logs/_qa_round11b_hi.txt`, `logs/_qa_round11b_model_state_final.txt`
