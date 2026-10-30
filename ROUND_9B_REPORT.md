# Round 9B report — restore, thermal check, fair re-measure

Date: 2026-10-30. Model: Qwen3-30B-A3B-GGUF (production options). Task: `tasks/ROUND_9B_RESTORE_AND_REMEASURE.md`.

## Why 9B

Round 9 final numbers were taken after Part 6 left a slow generation state (~6.5–7 tok/s). Architect correction (30 Oct 13:15): on Windows/Vulkan, high `llama-server` RSS mirrors shared GPU memory and is **not** a slowness signal. Verdict is tok/s ≥ 11 on a realistic ~6k system+tools probe. Leading alternate hypothesis was thermal throttling (Part 1b).

## Verdict (decision rules)

| Gate | Result |
|---|---|
| Safety 100% | **PASS** (`logs/round9b_quick.json`, safety=PASS) |
| Battery ≥ baseline − 1 (16→≥15) | **FAIL** — default **11/20** (`logs/round9b_battery_default.json`) |
| Round as a whole | **NOT kept** (battery gate failed even under OK tok/s) |

Fair speed under OK state is close to Round 9 **baseline**, not the confounded final. Battery pass count did not recover; regression vs baseline is not explained by the Part 6 slow state alone.

### Per-part decisions

| Part | Criterion | Measured | Decision |
|---|---|---|---|
| 1 Model-state guard | tok/s ≥ 11 realistic probe | OK at 13.175 tok/s (`logs/model_state_20261030-093829.json`) | **Keep** |
| 1b Thermal | ≥25% tok/s drop over 12 min + recovery | drop 0.0%; not thermal (`logs/round9b_thermal.json`) | Evidence only |
| 2 Data cards + listing | tests; no false Corrected; card persists | offline tests PASS | **Keep** (architect hand-test for UI) |
| 3 Early abort (synthesis-only) | battery mean wall ≤ baseline − 8% **and** passes ≥ 15 | early-abort 46.13 s / 12/20 vs default 42.56 s / 11/20 | **Not kept** — default `MINIAI_EARLY_ABORT=off` |
| 4 Cache-stable | wall not worse >3% | case (c) mean 5.43 s vs Round 9 baseline 16.37 s | **Keep** (`MINIAI_CACHE_STABLE=on`) |
| 5 Warm-up | cold first-token ≥30% better | 15.22 → 14.76 s (~3%) | Criterion failed; warm-up code left on |
| 5 Slow-state UI | chip + restore | shipped | **Keep** |

## Restore results

From `logs/round9b_restore.json` (still using the pre-correction RSS+tok/s rule at capture time):

| | Verdict (old rule) | tok/s | RSS GB | free RAM GB |
|---|---|---:|---:|---:|
| Before | DEGRADED | 15.979 | 10.605 | 3.513 |
| After | DEGRADED | 16.154 | 10.589 | 3.654 |

After architect Correction (tok/s-only): **OK** at 13.175 tok/s, prompt_tokens=6155, RSS 10.601 GB logged only — `logs/model_state_20261030-093829.json`. Later checks during Part 4 remained OK (~13 tok/s).

## Part 1b — thermal

Power plan: Balanced (`powercfg /getactivescheme` in `logs/round9b_thermal.json`).

| Minute | Mean tok/s (calls in that minute) |
|---:|---:|
| 0 | 12.493 |
| 1 | 12.751 |
| 2 | 12.563 |
| 3 | 12.648 |
| 4 | 12.837 |
| 5 | 12.877 |
| 6 | 12.742 |
| 7 | 12.884 |
| 8 | 12.916 |
| 9 | 12.901 |
| 10 | 12.904 |
| 11 | 12.825 |

First call 12.729 → last 12.725 (drop 0.0%). Recovery after 10 min idle: 13.319, 13.191, 13.228. **Not thermal** by the ≥25% rule. Slowness has another cause.

## Before / after metrics (baseline = Round 9 pre-Part-6)

### Quick suite

| | Pass | Safety | Log |
|---|---:|---|---|
| Round 9 baseline | 15/16 | PASS | `logs/round9_baseline_quick.json` |
| Round 9B | **15/16** | PASS | `logs/round9b_quick.json` |

### QA battery (20 tasks)

| | Pass | Mean wall_s | Log |
|---|---:|---:|---|
| Round 9 baseline | 16/20 | 58.06 | `logs/round9_baseline_battery.json` |
| Round 9 final (slow, confounded) | 13/20 | 92.35 | `logs/round9_final_battery.json` |
| Round 9B default (early abort off) | **11/20** | **42.56** | `logs/round9b_battery_default.json` |
| Round 9B early abort on | 12/20 | 46.13 | `logs/round9b_battery_early_abort.json` |

Default fails: `qa_e_list_folder`, `qa_h_code_cli`, `qa_h_code_debug`, `qa_h_multistep`, `qa_m_code_small`, `qa_m_duplicates`, `qa_m_organise`, `qa_m_pdf_question`, `qa_s_injection_page`.

With early abort on, `qa_h_code_debug` and `qa_m_duplicates` **passed** (synthesis-only fix), but overall wall did not improve ≥8% and passes stayed <15.

### Real-speed probe (`measure_real_speed.py` ×3, `--six-turn`)

| Case | Round 9 baseline mean | Round 9 final (slow) | Round 9B mean | Log |
|---|---:|---:|---:|---|
| (a) 3 biggest files | 17.02 | 34.94 | **18.83** | `logs/round9b_speed.json` |
| (b) RAM vs storage | 8.77 | 27.41 | **14.66** | same |
| (c) 2-turn codeword | 16.37 | 8.34 | **5.43** | same |
| (d) 6-turn | — | 16.67 | **11.83** | same |

Model state at speed start: OK, tok/s=13.168 (`logs/round9b_speed.json` → `model_state`).

### First-token

| Mode | first_token_s | Log |
|---|---:|---|
| No warm-up | 15.215 | `logs/round9b_first_token_no_warmup.json` |
| App-path warm-up | 14.765 | `logs/round9b_first_token_warmup.json` |

Improvement ≈ 3% (need ≥30%).

## Flags after Round 9B

| Flag | Value |
|---|---|
| `MINIAI_EARLY_ABORT` | **off** |
| `MINIAI_CACHE_STABLE` | **on** |
| Data cards | **on** |
| Warm-up | **on** (product behaviour; keep rule unmet) |
| Model-state refuse on measure | **on** (tok/s ≥ 11; RSS logged only) |

## Commit hashes

| Part | Hash | Subject |
|---|---|---|
| 1 | `d6fe742` | Round 9B Part 1 — model-state guard (tok/s verdict, realistic probe) |
| 1b | `70b2882` | Round 9B Part 1b — sustained-load thermal check (not thermal) |
| 2 | `670cbf4` | Round 9B Part 2 — keep data cards, strip re-lists, listing match |
| 3 | `5fca459` | Round 9B Part 3 — early abort only on synthesis calls |
| 4 | `3ab72f9` | Round 9B Part 4 — fair re-measure under OK model state |
| 5 | `6741d91` | Round 9B Part 5 — slow-state chip and in-app model reload |
| Report | *14662bcb8b847703c79e3135c11137d76bb627cc* | Round 9B report |

## Finish

- Restarted MiniAI (`python -m app`); window title MiniAI present (pid 18400).
- `check_model_state` = **OK** (tok/s=13.022, RSS=11.053 GB logged only; prompt_tokens=6155).
- "Hi" → `Hello! How can I assist you today?` (`logs/_qa_round9b_hi.txt`).

