# Round 11 report — plan-first for long tasks

Date: 2026-10-31. Task: `tasks/ROUND_11_PLANNER.md`.

## Part 0 — Groq provider (opt-in, planner-only)

| Item | Result |
|---|---|
| Key store | DPAPI `%LOCALAPPDATA%\MiniAI\secrets\groq.bin` |
| Settings | Paste / Save / Test / Remove + Planner Off / On this PC / Groq |
| Host lock | `api.groq.com` only; model `openai/gpt-oss-120b` |
| Payload | System + user text (`~` for home) + **tool names** only — no tools, files, memory, history |
| Quota | Local RPM 30 / RPD 1000 / TPM 8000 / TPD 200k; respects `retry-after`; 429 → local fallback note |
| Footprint | Each Groq request listed (time via ledger, bytes, model) |
| Redaction | `gsk_…` + stored Groq key in `log_redact` |
| Offline | `scripts/test_round11_part0.py` **FAILURES=0** |

Commit: `36c7a0a`

## Part 1 — planner

| Item | Result |
|---|---|
| `needs_plan` | Multi-step verbs / `project`\|`app` / `and then` / ≥140 chars + verb; never easy chat |
| Plan JSON | ≤8 steps: `step`, `tool_hint`, `done_when` |
| Local | Same message 0 + tools (cache-safe); planning system msg after user; thinking on; ignore tool calls; retry once |
| Groq | Same JSON; 20 s; on failure → local + note |
| Finish guard | Once per planned turn |
| Env | `MINIAI_PLANNER=off\|local\|groq` |
| Offline | `scripts/test_round11_part1.py` **FAILURES=0** |

Commit: `272bea6`

## Part 2 — UI checklist

Plan checklist under the turn header (`.plan-check`, v2 tokens). Ticks use `--verdigris` when the finish-guard marks a step done.

Capture (via `miniai_capture.py` only): `app/design/actual_v14_plan_checklist.png`

Offline: `scripts/test_round11_part2.py` **FAILURES=0**. Commit: `cf72c00`

## Part 3 — measure

**Targets:** `qa_h_code_cli`, `qa_h_multistep`, `qa_m_organise`  
**Guards:** `qa_h_code_debug`, `qa_h_code_website`, `qa_m_code_small`

**Groq mode:** skipped — no Groq key saved (`has_key=False`).

### Scoreboard (×3 each task → /9)

| Mode | Targets | Guards | Mean wall (targets) | Log |
|---|---:|---:|---:|---|
| **off** | **1/9** | **8/9** | **104.173 s** | `logs/round11_off_targets.json` |
| **local** | **0/9** | **6/9** | **167.113 s** | `logs/round11_local_targets.json` |
| groq | skipped | — | — | no key |

Per-task passes:

| Task | off | local |
|---|---:|---:|
| qa_h_code_cli | 0/3 | 0/3 |
| qa_h_multistep | 0/3 | 0/3 |
| qa_m_organise | 1/3 | 0/3 |
| qa_h_code_debug | 2/3 | 1/3 |
| qa_h_code_website | 3/3 | 3/3 |
| qa_m_code_small | 3/3 | 2/3 |

### Keep rule (pre-registered)

Keep only if: targets ≥ off+3, guards ≥ off−1, battery×2 mean ≥ 14.5, safety 100%, mean wall targets ≤ 1.5×off.

| Gate | Need | local | Met? |
|---|---|---|---|
| Targets ≥ off+3 | ≥ **4**/9 | 0/9 | **no** |
| Guards ≥ off−1 | ≥ **7**/9 | 6/9 | **no** |
| Wall ≤ 1.5×off | ≤ **156.26 s** | 167.11 s | **no** |
| Battery ×2 / safety | — | not run (mode failed gates) | — |

**No mode kept. Default remains Planner = Off.** (`MINIAI_PLANNER` / prefs `planner_mode` = `off`)

Full battery ×2 and quick suite for a winning mode: **not run** (no winner).

### Target answers (quoted)

#### off — `logs/round11_off_targets_eval.json`

**qa_h_code_cli** (0/3):
1. `Tests: 1 passed, 3 failing: fail test_add_expense … fail test_category_totals … fail test_list_expenses …`
2. `Tests: 1 error(s): collection — … ImportError while importing test module …`
3. `Tests: 5 failing: fail test_initialization … fail test_add_expense …`

**qa_h_multistep** (0/3):
1. `The summary.md file has been created… Best Month: May… Worst Month: April…` (grader: total revenue miss)
2. Similar summary content; total check failed
3. Similar summary content; total check failed

**qa_m_organise** (1/3):
1. `You declined, so nothing was changed…` → fail
2. `The folder has been successfully organized… Documents / Images / Executables…` → **pass**
3. `You declined, so nothing was changed…` → fail

#### local — `logs/round11_local_targets_eval.json`

**qa_h_code_cli** (0/3): failing pytest / empty tests / pyproject error (see eval JSON).

**qa_h_multistep** (0/3):
1. `Tests: status unknown (time budget nearly exhausted).`
2. Pandas install denied; alternative approach prose
3. `summary.md` written with May/April; still graded fail

**qa_m_organise** (0/3): all three declined folder creation / no moves completed.

### Wall times (targets mean)

| Mode | Mean wall (s) |
|---|---:|
| off | 104.173 |
| local | 167.113 (1.60× off; over 1.5× gate) |

### Groq usage

0 requests / 0 tokens (no key; mode skipped).

## Decisions

1. **Planner default: Off** — local did not beat off on targets (+0 vs need +3) and was slower and weaker on guards.
2. Groq remains an opt-in Settings choice when a key is saved; not measured this round.
3. Production brain unchanged: `Qwen3-30B-A3B-GGUF`.

## Commit hashes

| Part | Hash |
|---|---|
| 0 Groq provider | `36c7a0a` |
| 1 planner | `272bea6` |
| 2 UI checklist | `cf72c00` |
| 3 measure + this report | `b858adb6e106cd351a206dcde09a6409a6016d9c` |

## Finish

- MiniAI restarted (`python -m app`); window title MiniAI (pid 25000).
- Planner prefs/default **off**.
- `check_model_state` = **OK** — tok/s=12.51 ≥ 11.98 (`logs/_qa_round11_hi.txt`).
- “Hi” → `Hello! How can I assist you today?`

