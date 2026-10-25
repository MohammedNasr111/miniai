# Round 6 Part 5 — pre-registered keep/disable rule

Copied into ROUND_6_REPORT.md **before** the measurement battery runs.

## Rule (verbatim from tasks/ROUND_6_HARD_TASKS.md)

Keep each Part's change only if:

1. its target tasks improve by **≥ 2 passes in total** vs the round-4 baseline below, AND
2. no other task drops by more than **1 pass**, AND
3. safety stays **100%**.

If a Part fails the rule, disable it behind a setting (default off). Don't delete it, and report.

Report time cost per Part (mean wall on its target tasks).

## Round-4 baseline (QA round 4, smart)

| Tier | Passes |
|------|--------|
| easy | 15/15 |
| medium | 20/21 |
| hard | 13/24 |

Target-task baselines (passes out of 3):

| Part | Target task(s) | R4 passes/3 |
|------|----------------|-------------|
| 1 analyze_table | qa_h_multistep | 0/3 |
| 2 coding loop | qa_h_code_cli + qa_h_code_debug | 0/3 + 0/3 |
| 3 research pipeline | qa_h_research_report | 1/3 |
| 4 PDF citations | qa_m_pdf_question | 2/3 |

Hard failures called out in the task brief: cli/debug/multistep 0/3, research 1/3; pdf 2/3.

## Feature flags (disable = default off after failed keep)

- `FEATURE_ANALYZE_TABLE` / `MINIAI_FEATURE_ANALYZE_TABLE`
- `FEATURE_CODING_AUTO_TEST` / `MINIAI_FEATURE_CODING_AUTO_TEST` (also gates slug/find behaviour used with Part 2; core tools remain registered but auto-test + related loop hooks respect the flag where implemented)
- `FEATURE_RESEARCH_PIPELINE` / `MINIAI_FEATURE_RESEARCH_PIPELINE`
- `FEATURE_PDF_CITATIONS` / `MINIAI_FEATURE_PDF_CITATIONS`

Recorded before run: 2026-10-25 (local).
