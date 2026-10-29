# Round 9 report — speed, cache, data-not-prose

Date: 2026-10-30. Model: Qwen3-30B-A3B-GGUF (production options). Review context: `docs/REVIEW_2026-10-29.md`. Task: `tasks/ROUND_9_SPEED_DATA_UI.md`.

## Verdict

| Gate | Result |
|---|---|
| Safety 100% | **PASS** (`logs/round9_final_quick.json` safety=PASS, 9/9) |
| Battery ≥ baseline − 1 (16→≥15) | **FAIL** — final **13/20** (`logs/round9_final_battery.json`) |
| Round as a whole | **NOT kept** (battery gate failed) |

Attribution (battery pass counts):

| Run | Pass | Log |
|---|---:|---|
| Baseline | 16/20 | `logs/round9_baseline_battery.json` |
| All-on (Parts 1–5) | 13/20 | `logs/round9_final_battery.json` |
| `MINIAI_EARLY_ABORT=off` | 12/20 | `logs/round9_attr_early_abort_off.json` |
| `MINIAI_CACHE_STABLE=off` | 13/20 | `logs/round9_attr_cache_stable_off.json` |

Neither Part 3 nor Part 4 alone restored the pass count. Extra fails vs baseline were mostly coding / organise / pdf / injection (model noise + fixture behaviour), not clearly caused by those flags.

### Per-part keep rules

| Part | Criterion | Measured | Decision |
|---|---|---|---|
| 1 Listing N | tests pass | `scripts/test_listing_honesty.py` | **Keep** |
| 2 Data cards | tests pass; architect hand-test | `scripts/test_data_cards.py` PASS | **Keep** (UI hand-test for architect) |
| 3 Early abort | battery mean wall ≤ baseline − 8% | baseline mean 58.1 s → final 92.3 s (**worse**) | **Not kept** — default `MINIAI_EARLY_ABORT=off` |
| 4 Cache-stable | multi-turn cache improves; wall not worse >3% | case (c) wall 16.4→8.3 s; turn1 `cache_n` 16→6133 | **Keep** (`MINIAI_CACHE_STABLE=on`) |
| 5 Warm-up | cold first-token ≥30% better | 24.57 s → 22.83 s (~7%) | **Criterion failed**; warm-up code left on (low risk, correct product behaviour) |
| 6 Bandwidth | evidence only | see table below | N/A (no keep flag) |

## Before / after metrics

### Quick suite

| | Pass | Safety | Log |
|---|---:|---|---|
| Baseline | 15/16 | PASS | `logs/round9_baseline_quick.json` |
| Final | **16/16** | PASS | `logs/round9_final_quick.json` |

### QA battery (20 tasks)

| | Pass | Mean wall_s | Log |
|---|---:|---:|---|
| Baseline | 16/20 | 58.06 | `logs/round9_baseline_battery.json` |
| Final (all-on) | 13/20 | 92.35 | `logs/round9_final_battery.json` |

Final fails: `qa_h_code_cli`, `qa_h_multistep`, `qa_m_code_small`, `qa_m_duplicates`, `qa_m_organise`, `qa_m_pdf_question`, `qa_s_injection_page`.

### Real-speed probe (`measure_real_speed.py` ×3)

| Case | Baseline mean wall_s | Final mean wall_s | Logs |
|---|---:|---:|---|
| (a) 3 biggest files | 17.02 | 34.94 | `logs/round9_baseline_speed.json` / `logs/round9_final_speed.json` |
| (b) RAM vs storage | 8.77 | 27.41 | same |
| (c) 2-turn codeword | 16.37 | **8.34** | same |
| (d) 6-turn | (not in baseline) | 16.67 | `logs/round9_final_speed.json` (`--six-turn`) |

Case (c)/(d) `cache_n` (timings; `prompt_tokens` often absent on stream chunks):

- Baseline (c) turn1 `cache_n=16`, turn2 `cache_n=6171` (`logs/round9_baseline_speed.json`).
- Final (c) turn1 `cache_n=6133`, turn2 `cache_n=6171` (`logs/round9_final_speed.json`).
- Final (d) `cache_n` sequence 6135→6145→6162→6179→6196→6213 (prefix held).

### First-token (Part 5)

| Mode | first_token_s | Log |
|---|---:|---|
| No warm-up | 24.567 | `logs/round9_first_token_no_warmup.json` |
| App-path warm-up | 22.830 | `logs/round9_first_token_warmup.json` |

Improvement ≈ 7% (need ≥30% to keep by rule).

## Part 0 — stalls (`stall_s > 10`)

In `logs/round9_baseline_speed.json` and `logs/round9_final_speed.json`, **no** llm_call had `stall_s > 10`.

Notable baseline (c) turn1 (not >10 but high paging): `stall_s=2.827`, `lemonade_page_faults_delta=92838`, free RAM before/after 4.68→4.38 GB (`logs/round9_baseline_speed.json`).

System snapshot at Part 0: `logs/round9_system.json` (Lemonade 11.9.0, GPU dedicated/shared counters, top RSS, RAM).

## Part 6 — bandwidth

Source: `logs/round9_bandwidth.md` / `logs/round9_bandwidth.json`.

| Model | mean tok/s | file GB | mean effective GB/s | vs 44.8 GB/s |
|---|---:|---:|---:|---:|
| Qwen3-14B-GGUF | 3.988 | 7.956 | 31.727 | 71% |
| Qwen3-30B-A3B-GGUF | 16.066 | 16.186 | 28.137 | 63% (lower bound) |

Assumptions documented in that file. Apps left open. Restored 30B-A3B; Hi ok in the same probe.

## Final flags

| Flag | Default after Round 9 |
|---|---|
| `MINIAI_EARLY_ABORT` | **off** (Part 3 not kept) |
| `MINIAI_CACHE_STABLE` | **on** (Part 4 kept) |
| Data cards / listing N / warm-up code | **on** (Parts 1–2 kept; Part 5 code retained) |

## Commit hashes

| Part | Hash | Subject |
|---|---|---|
| 0 | `e9b52d3` | Round 9 Part 0 — instrumentation and baseline measurements |
| 1 | `4b34801` | Round 9 Part 1 — fix listing top-N from the question |
| 2 | `89ec601` | Round 9 Part 2 — data cards for list_directory and search_files |
| 3 | `e3e44b7` | Round 9 Part 3 — early abort discarded thinking-off drafts |
| 4 | `642cad1` | Round 9 Part 4 — cache-stable prompt history compression |
| 5 | `ab0d754` | Round 9 Part 5 — warm-up with system prompt and tools |
| 6 | `749df9f` | Round 9 Part 6 — bandwidth probe for 14B and 30B-A3B |
| 7 | *(this commit)* | Round 9 Part 7 — final measure, flags, report |

## Restart / Hi

MiniAI was (re)started via `pythonw -m app.main`. App-path chat answered **Hi** with: `Hello! How can I assist you today?`
