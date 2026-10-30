# Round 9D Part 3 — bisect table

Worktrees under `C:\Users\mohdc\miniai_bisect\`. Runner: `scripts/round9d_bisect_run.py`
(`MINIAI_EARLY_ABORT=off`, model-state guard from main tree, `--force` only when the
worktree's `eval.run` supports it).

## Pass counts (code_small / pdf)

| Commit | Subject | code_small | pdf | Log JSON |
|---|---|---|---|---|
| `e9b52d3` | Round 9 Part 0 baseline | **2/2** | 0/2 | `logs/round9d_bisect_e9b52d3.json` |
| `4b34801` | Round 9 Part 1 listing top-N | **0/2** | 2/2 | `logs/round9d_bisect_4b34801.json` |
| `89ec601` | Round 9 Part 2 data cards | **0/2** | 0/2 | `logs/round9d_bisect_89ec601.json` |
| `e3e44b7` | Round 9 Part 3 early abort | **0/2** | 1/2 | `logs/round9d_bisect_e3e44b7.json` |
| `5fca459` | Round 9B Part 3 early-abort scope | **1/2** | 1/2 | `logs/round9d_bisect_5fca459.json` |
| `bd33f41` (HEAD Part 2) | diagnose | **0/2** (Part 2 diag) | 0/2 | `logs/round9d_part2_diag.json` |

## ×3 confirmation (parent vs first 0/2)

| Commit | code_small | pdf | Log JSON |
|---|---|---|---|
| `e9b52d3` (parent of first 0/2) | **1/3** | **3/3** | `logs/round9d_bisect_e9b52d3_x3.json` |
| `4b34801` (first measured 0/2) | 0/2 only (×2); not re-run ×3 after parent failed confirm | 2/2 | `logs/round9d_bisect_4b34801.json` |

## Verdict

**No Round 9 commit is proven as the sole `code_small` culprit.**

- Binary search first hit `0/2` at `4b34801` (listing honesty only — no coding/tool path change).
- Confirming the parent `e9b52d3` at ×3 yields only **1/3** passes for `code_small`, so the
  baseline itself is flaky under the same runner. Listing-honesty cannot be blamed.
- Failure mode matches Part 2 on every bad run: relative `create_folder` → protected-path
  error; model often fails to recover with `ws_write`; Desktop `create_folder` is denied by
  the harness (`answer_by_action` default `"no"`, YAML omits `create_folder`).
- `qa_m_pdf_question` is also flaky at baseline (0/2 then 3/3); Part 2 shows setup
  `index_documents` runs **outside** `answer_by_action`, so indexing can be denied silently.

**Actionable fix (Part 4):** harness + protected-path hint for coding recovery — not a
revert of Round 9 Part 1–3 product commits.
