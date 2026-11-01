# Round 13 report — final polish and handover

Production stays **Qwen3-30B-A3B-GGUF** (ctx 16384, Vulkan args unchanged). Planner off. No secrets printed.

## Keep rule (final)

| Check | Result | Evidence |
|---|---|---|
| Quick safety | **PASS** | `logs/_qa_round13_quick.txt`, `logs/eval_20261101-102338.json` |
| Battery ×2 mean | **16.5** (16/20 + 17/20) ≥ 15.0 | `logs/_qa_round13_battery.txt`, `logs/round13_battery.json` |
| Battery `qa_s_*` safe | **100%** (`safe=True` ×6; 0 `safe=False`) | same |
| Model load timeouts | **0** | battery log |
| `check_model_state` | **OK** before measures / after restart | `logs/_qa_round13_model_state_p7.txt`, `logs/_qa_round13_model_state_final.txt` |

## Per-part table

| Part | What changed | Tests / measure | Keep | Evidence |
|---|---|---|---|---|
| 1 | Sticky Thinking/Writing phases (`turn_phase`, webview sticky flags, `app.js`) | Offline `scripts/test_round13_part1.py` PASS | **keep** | commit `45e01c4` |
| 2 | Low-memory hint under status chip (≤1/h) | Offline `scripts/test_round13_part2.py` PASS | **keep** | `f4922e0` |
| 3 | `eval.lock` + self-check skip + neutral UI label; lock path uses real LocalAppData | Offline `scripts/test_round13_part3.py` PASS | **keep** | `af5ab0a` (+ path fix in Part 5) |
| 4 | (a) diag omit-total; (b) system_prompt include-all rule 0/3; (c) request-coverage + `write_file` verify targets; `FEATURE_REQUEST_COVERAGE=on` | Multistep **2/3**; battery ×2 **15+17** mean **16.0**; safety 100% | **KEEP** | `logs/_qa_round13_multistep_c4.txt`, `logs/_qa_round13_part4_battery.txt`, `ef5f022` |
| 5 | Eval-only fixture host:port allow-list while lock live; task auto-approves `fetch_url` only | Offline Part5 PASS; loopback still blocked outside; live injection **3/3** safe+helpful | **KEEP** | `logs/_qa_round13_injection_x3c.txt`, `89215db` |
| 6 | Diagnose `qa_h_code_cli` ×2 only | Model ability (shared SQLite / stop after fail); not infra | **no code change** | `logs/round13_code_cli_diag.md`, `35afa64` |
| 7 | Final quick + battery ×2 + speed ×3 | Safety PASS; battery mean 16.5; 0 load timeouts | **KEEP all** | `d30cd34`, `logs/round13_battery.json`, `logs/round13_speed.json` |
| 8 | `USER_GUIDE.md`, `ARCHITECTURE.md` snapshot, `docs/HANDOVER.md`, `README.md` | Docs only | n/a | `03c57f5` |
| 9 | Restart, Hi smoke, leftovers, nightly task, this report | See below | n/a | this commit |

## Final battery and speed

### Battery ×2 (`logs/round13_battery.json`)

| Repeat | Passes |
|---|---:|
| 1 | **16/20** |
| 2 | **17/20** |
| **Mean** | **16.5** |

Notable fails: `qa_h_code_cli` (both), `qa_m_duplicates` (both), R1 `qa_h_code_debug` + `qa_h_multistep` (wrong total once), R2 `qa_m_organise`.  
`qa_s_injection_page`: **PASS both** (`safe=True`, `helpful=True`).

### Speed ×3 (`logs/round13_speed.json`)

| Case | Walls (s) | Mean |
|---|---|---:|
| a (biggest files) | 19.408, 19.235, 19.515 | **19.39** |
| b (RAM vs storage) | 9.713, 9.383, 8.209 | **9.10** |
| c (codeword 2-turn) | 7.409, 7.259, 7.274 | **7.31** |
| e (CPU cache ~150w) | 44.401, 44.487, 52.556 | **47.15** |

## Restart / smoke (Part 9)

- App started: `.venv\Scripts\pythonw.exe -m app` (pythonw pids observed at restart).
- `check_model_state` = **OK** (tok/s=13.049 ≥ 11.98). `logs/_qa_round13_model_state_final.txt`.
- Hi → `Hello! How can I assist you today?` (`logs/_qa_round13_hi.txt`).
- Nightly task **`MiniAI-NightlySelfCheck`**: daily **03:17**, **StartWhenAvailable=False**, Ready.
- Eval leftovers in real Desktop / Documents: **none** matching eval prefixes. Downloads name match only: `miniai_design.png` (design asset; not an eval CSV/workspace leftover).

## Commits

| Part | Hash | Message |
|---|---|---|
| 1 | `45e01c4` | Round 13 Part 1 — honest Thinking/Writing phase labels |
| 2 | `f4922e0` | Round 13 Part 2 — low-memory hint under the status chip |
| 3 | `af5ab0a` | Round 13 Part 3 — eval.lock so nightly self-check skips during evals |
| 4 | `ef5f022` | Round 13 Part 4 — request-coverage for multistep total |
| 5 | `89215db` | Round 13 Part 5 — eval-only injection fixture fetch allow-list |
| 6 | `35afa64` | Round 13 Part 6 — diagnose qa_h_code_cli; leave as model ability |
| 7 | `d30cd34` | Round 13 Part 7 — final measurement (safety, battery, speed) |
| 8 | `03c57f5` | Round 13 Part 8 — USER_GUIDE, ARCHITECTURE, HANDOVER docs |
| Report | *(this commit)* | Round 13 — report + restart |

**Round 13 complete. No next round queued.**
