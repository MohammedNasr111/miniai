# Round 6 Part 5 — keep/disable decisions

Battery: `logs/_qa_round6_battery.txt` / `logs/eval_20261025-141533.json`
Quick: `logs/_qa_round6_quick.txt` (Safety: PASS)

## Totals

| Tier | R4 | R6 |
|------|----|----|
| easy | 15/15 | 15/15 |
| medium | 20/21 | 17/21 |
| hard | 13/24 | 18/24 |
| QA safety (3×3) | 9/9 | 9/9 |

## Target deltas

| Part | Target | R4 | R6 | Δ | ≥2? |
|------|--------|----|----|---|-----|
| 1 | qa_h_multistep | 0/3 | 0/3 | 0 | no |
| 2 | cli + debug | 0+0 | 0+3 | +3 | yes |
| 3 | qa_h_research_report | 1/3 | 3/3 | +2 | yes |
| 4 | qa_m_pdf_question | 2/3 | 3/3 | +1 | no |

## Collateral

- qa_m_organise: 3/3 → 0/3 (Δ −3) — **violates** “no other task drops by more than 1”
- qa_m_duplicates: 3/3 → 2/3 (Δ −1) — allowed
- Safety: 100%

## Decisions (pre-registered rule)

Because the battery includes a task drop of more than 1 pass (`qa_m_organise`), **every Part fails the keep rule** even where targets improved. Defaults set to **off**:

| Part | Decision | Flag |
|------|----------|------|
| 1 analyze_table | DISABLE | `FEATURE_ANALYZE_TABLE=off` |
| 2 coding loop | DISABLE | `FEATURE_CODING_AUTO_TEST=off` |
| 3 research pipeline | DISABLE | `FEATURE_RESEARCH_PIPELINE=off` |
| 4 PDF citations | DISABLE | `FEATURE_PDF_CITATIONS=off` |

Code retained; re-enable via `MINIAI_FEATURE_*=on`.

## Mean wall on targets (R6)

| Task | mean wall_s |
|------|-------------|
| qa_h_multistep | 178.8 |
| qa_h_code_cli | 221.9 |
| qa_h_code_debug | 76.5 |
| qa_h_research_report | 258.3 |
| qa_m_pdf_question | 52.0 |
