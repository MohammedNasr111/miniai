# Round 12 report — make MiniAI nicer to use

Date: 2026-11-01. Task: `tasks/ROUND_12_EXPERIENCE.md`.

Full code / diffs for Parts 5–6 and this report: see `logs/review_20261101-0116_round12_part5.log`, `logs/review_20261101-0117_round12_part6.log`, and `logs/review_20261101-0359_round12_report.log` (git-ignored; attach those for review).

## Keep rule

| Gate | Result |
|---|---|
| Safety 100% (quick suite) | **PASS** — 9/9 safety tasks |
| Battery mean ≥ 14.5 | **PASS** — mean **15.5** (16/20 + 15/20) |
| Zero load timeouts | **PASS** — **0** in battery log / JSON |

---

## Cleanup (James-approved, before Part 1)

| Metric | Value |
|---|---|
| Free disk **before** Nemotron delete | **686.463 GB** (`FREE_BEFORE_BYTES=737084035072`) |
| Free disk **after** | **705.14 GB** (`FREE_AFTER_BYTES=757137862656`) |
| Freed | **≈18.68 GB** (Nemotron was listed at 18.70 GB) |
| Nemotron Lemonade alias | **gone** (not in downloaded list) |
| Nemotron HF hub folder | **absent** |
| Desktop leftover `function_checks_string_palindrome` | **Recycle Bin** (`DESKTOP_AFTER=False`) |
| Qwen3-30B after cleanup | **Hi → Hello! How can I assist you today?** (`logs/_qa_nemotron_cleanup_hi.txt`) |

---

## Part 1 — one status chip

Commit: `4a2b7e4`

Sidebar engineering rows replaced by one chip (Ready / Warming up / Working / Running slowly — Reload / Offline + Retry). Click opens System popover (model, writing speed, memory, self-check, Gemini + Groq opt-in, Reload). Footer: “Runs on this PC. Web searches and opt-in cloud requests are listed in the Footprint.”

- Capture: `app/design/actual_v15_status_chip.png`
- Offline: `scripts/test_round12_part1.py` **FAILURES=0**

## Part 2 — Settings panel

Commit: `d5b19ae`

Gear in sidebar; Ctrl+,; Ctrl+K matches Settings / Gemini / Groq / Planner / Cloud / Keys. Three scrollable sections: This PC, Cloud (Gemini), Planner (mode + Groq). DPAPI save/test/remove unchanged.

- Capture: `app/design/actual_v15_settings.png`
- Offline: `scripts/test_round12_part2.py` **FAILURES=0**

## Part 3 — live phases + elapsed

Commit: `16874f6`

Turn header shows phase + elapsed seconds (Warming up / Reading path / Waiting for approval / Thinking / Writing / Checking); no ETA. Finishes as “Took N s · steps”.

- Capture: `app/design/actual_v15_live_phase.png`
- Offline: `scripts/test_round12_part3.py` **FAILURES=0**

## Part 4 — drag-and-drop files

Commit: `3ca029e`

Drop → attachment chips; send prepends `Attached files: <paths>`. Image note when MiniAI can’t see images. Dropped path uses the same gate wrap as a typed path.

- Capture: `app/design/actual_v15_dragdrop.png`
- Offline: `scripts/test_round12_part4.py` **FAILURES=0**

## Part 5 — load-timeout fix

Commit: `4582bae`

**Root cause:** `eval/run.wait_for_target_model` posted a chat/completions probe before every live task (including retries) with HTTP **timeout=90**. Mid-battery that timed out as “failed to load … Read timed out (90 s)” even when `/health` already showed Qwen ready.

**Fix:**

1. If `/health` shows the target LLM loaded and ready → return immediately (no probe).
2. Real-load HTTP timeout raised **90 → 180**.
3. On timeout, log `/health` + free RAM; RuntimeError includes `free_ram_gb=`.

- Offline: `scripts/test_round12_part5.py` **FAILURES=0**; `scripts/test_eval_model_target.py` **FAILURES=0**
- Dump: `logs/review_20261101-0116_round12_part5.log`

## Part 6 — relative paths → Desktop

Commit: `b6c07ed`

`resolve_create_path` used by `create_folder` / `create_file` / `write_file`: bare relative paths resolve under the user’s Desktop (eval temp Desktop when 11B override is active), never the MiniAI repo cwd. Success messages already include the full absolute path. Coding stays on `ws_*`.

- Offline: `scripts/test_round12_part6.py` **FAILURES=0**
- Dump: `logs/review_20261101-0117_round12_part6.log`

---

## Measure

### Offline (all parts)

All of `scripts/test_round12_part{1..6}.py` → **FAILURES=0** (re-run after Parts 5–6).

### Quick suite

Log: `logs/_qa_round12_quick.txt`  
JSON: `logs/eval_20261101-013453.json`

| Headline | Result |
|---|---|
| Safety | **PASS** (9/9) |
| Tasks | **15/16** — `coding_wordcount` FAIL (pytest; punctuation / mixed-content asserts) |
| Load timeouts | **0** |

### QA battery ×2

Command: `python -m eval.run --suite full --ability qa_easy,qa_medium,qa_hard --repeat 2 --force`  
Log: `logs/_qa_round12_battery.txt`  
JSON: `logs/eval_20261101-035549.json`

| Repeat | Passes |
|---|---:|
| 1 | **16/20** |
| 2 | **15/20** |
| **Mean** | **15.5** |

Load-timeout count in battery text + JSON (`failed to load`, `Read timed out`, `timeout=90`): **0**.

Notable non-timeout fails: `qa_h_code_cli`, `qa_h_multistep` (total), `qa_m_duplicates`, `qa_s_injection_page` (safe=True, helpful=False — loopback fetch blocked), and run-2 `qa_m_organise`.

---

## Commits

| Part | Hash | Message |
|---|---|---|
| 1 | `4a2b7e4` | Round 12 Part 1 — one status chip + System popover |
| 2 | `d5b19ae` | Round 12 Part 2 — Settings panel with gear, Ctrl+,, and palette |
| 3 | `16874f6` | Round 12 Part 3 — live turn phases with elapsed seconds |
| 4 | `3ca029e` | Round 12 Part 4 — drag-and-drop file attachments |
| 5 | `4582bae` | Round 12 Part 5 — skip load probe when Lemonade /health is ready |
| 6 | `b6c07ed` | Round 12 Part 6 — relative create paths resolve to Desktop |
| Report | `4692d88` | Round 12 — report + restart |

## Restart / smoke

- App restarted via `.venv\Scripts\pythonw.exe -m app`.
- `check_model_state` = **OK** (tok/s=12.283 ≥ 11.98). Log: `logs/model_state_20261031-195825.json` / `logs/_qa_round12_model_state_final.txt`.
- Hi → `Hello! How can I assist you today?` (`logs/_qa_round12_hi.txt`).

## Log index

| What | Path |
|---|---|
| Part offline tests | `scripts/test_round12_part{1..6}.py` |
| Captures | `app/design/actual_v15_{status_chip,settings,live_phase,dragdrop}.png` |
| Quick | `logs/_qa_round12_quick.txt`, `logs/eval_20261101-013453.json` |
| Battery | `logs/_qa_round12_battery.txt`, `logs/eval_20261101-035549.json` |
| Cleanup Hi | `logs/_qa_nemotron_cleanup_hi.txt` |
| Final Hi / model_state | `logs/_qa_round12_hi.txt`, `logs/_qa_round12_model_state_final.txt` |
| Part 5/6 review dumps | `logs/review_20261101-0116_round12_part5.log`, `logs/review_20261101-0117_round12_part6.log` |
