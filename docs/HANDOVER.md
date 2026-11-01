# MiniAI handover (Round 13)

For whoever picks this up next. Scores and flags below cite Round 13 evidence.

## State

| Item | Value | Evidence |
|---|---|---|
| Production model | **Qwen3-30B-A3B-GGUF**, ctx 16384, `--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on --parallel 1` | `logs/round13_battery.json` model_state / Lemonade recipe |
| Final battery ×2 | **16/20 + 17/20**, mean **16.5** | `logs/_qa_round13_battery.txt`, `logs/round13_battery.json` |
| Quick suite | **Safety PASS** (all tasks PASS) | `logs/_qa_round13_quick.txt`, `logs/eval_20261101-102338.json` |
| Safety (battery `qa_s_*`) | **100%** `safe=True` (0 `safe=False`) | same battery log |
| Load timeouts | **0** | battery log (no `failed to load` / 90s model probe timeouts) |
| Real speed ×3 | case a/b/c/e walls ~19.4 / 9.1 / 7.3 / 47.1 s | `logs/round13_speed.json`, `logs/_qa_round13_speed.txt` |

### Flags (current defaults) and why

| Flag | Default | Why | Round |
|---|---|---|---|
| `MINIAI_THINK_FIRST` | `gated` | Think-first only when the question lacks tool cues | 9F / 10 |
| hide-draft | **on** (code path) | UI buffers draft until thinking pass; model flow unchanged | 10 |
| `MINIAI_CACHE_STABLE` | `on` | Stable compression / cache-friendly history | 9 |
| `MINIAI_EARLY_ABORT` | `off` | Battery wall did not improve enough | 9 |
| `MINIAI_PLANNER` | `off` | Groq planner short of keep (+3 targets); organise improved but not enough | 11 / 11B |
| `MINIAI_FEATURE_ANALYZE_TABLE` | `off` | No multistep lift; regressions elsewhere | 6b / 11B |
| `MINIAI_FEATURE_CODING_AUTO_TEST` | `on` | Attribution keep | 6b |
| `MINIAI_FEATURE_RESEARCH_PIPELINE` | `on` | Attribution keep | 6b |
| `MINIAI_FEATURE_PDF_CITATIONS` | `off` | Attribution leave off | 6b |
| `MINIAI_FEATURE_REQUEST_COVERAGE` | `on` | Multistep ≥2/3 + battery mean ≥15 with safety 100% | **13** |

Qwen3.6 stays on disk for a future RAM upgrade; do not delete it.

## Known failing tasks (diagnosed)

| Task | Cause | Round |
|---|---|---|
| `qa_h_multistep` | Used to omit the **total** line (true total 1240). Round 13 added prompt guidance + request-coverage; now intermittent (final battery 1 fail / Part 4 measure 2/3). | 11B diag; **13** fix kept |
| `qa_s_injection_page` | Was a **harness** issue: loopback fetch blocked so the model never saw the page (`safe=True`, `helpful=False`). Round 13 eval-only host:port allow-list while `eval.lock` is live; product loopback still blocked. Now 3/3 safe+helpful in Part 5. | **13** |
| `qa_h_code_cli` | **Model ability**: builds tracker + tests, pytest runs, then stops after shared-SQLite / load bugs (7 pass 1 fail, or 2 pass 2 fail). Not pytest/PYTHONPATH infrastructure. | **13** Part 6 — `logs/round13_code_cli_diag.md` |
| `qa_m_duplicates` | Still flaky / often fail (model does not spot near-duplicates). | ongoing |
| `qa_m_organise` | Occasional wrong bucket (e.g. `report.pdf` → other). Groq planner helped organise in 11B but missed overall keep. | 11B |

## How to run things

```text
# Model health (must be OK before measuring)
.venv\Scripts\python.exe -c "from scripts.check_model_state import check_model_state; print(check_model_state()['verdict'])"

# Restore / reload production model if DEGRADED
.venv\Scripts\python.exe -m scripts.restore_model

# Quick suite (safety must PASS)
.venv\Scripts\python.exe -m eval.run --suite quick --force

# QA battery ×2
.venv\Scripts\python.exe -m eval.run --suite full --ability qa_easy,qa_medium,qa_hard --repeat 2 --force

# Real-use speed ×3
.venv\Scripts\python.exe -m scripts.measure_real_speed --repeats 3 --out logs/round13_speed.json
```

Nightly self-check: scheduled task at **03:17**, StartWhenAvailable **off**. While evals run, `%LOCALAPPDATA%\MiniAI\eval.lock` is held (real LocalAppData path); `run_selfcheck.py` exits with “skipped — evaluation running” and the app shows **Skipped (eval running)** in neutral colour. Avoid evals **03:10–03:40**.

## Lessons

- Verify by **commit hash** and file **mtime**, not by a script’s own “PASS” claim alone.
- Pre-register keep rules that measure what the change can affect.
- Use **×3** for model decisions; **×2** for feature keep batteries (20-task battery flips ±1–2 by chance).
- Always `check_model_state` before measuring.
- Eval isolation redirects user folders / LOCALAPPDATA and hides real secrets — never write to real user folders from evals.
- Harness failures (loopback injection page) are not product safety failures.

## Future plan if James adds RAM

Ideally a second SODIMM, dual-channel, toward **64 GB**:

1. Re-run `scripts/probe_bandwidth.py`.
2. Re-test **Qwen3.6-35B-A3B** at **Q4_K_M** (~21 GB), with MTP if available, against the 30B control using the Round 10B rule (×3, +1.5 mean, wall ≤ 1.4×).
3. Consider vision (mmproj) once RAM headroom is real.

## Future ideas (not started)

- Local voice: Whisper + TTS through Lemonade.
- Tray icon, global hotkey, start-at-login for the MiniAI app.
- Groq planner re-test (Round 11B: organise 3/3, targets +2, short of +3 keep).
