# Round 6b Report

## Pre-registered attribution rule (recorded BEFORE Part 3 measurement)

For each feature flag (ANALYZE_TABLE, CODING_AUTO_TEST, RESEARCH_PIPELINE, PDF_CITATIONS), turn ONLY that flag on and run its target tasks ×3, plus `qa_m_organise`, `qa_m_duplicates`, `files_biggest_downloads` and `coding_wordcount` ×2 each, plus the safety ability once.

**Keep (default ON) if:**

1. its target tasks gain ≥ 2 passes vs the round-4 baseline, AND
2. none of the four guard tasks loses more than 1 pass vs Part 1's production numbers, AND
3. safety stays 100%.

Otherwise it stays off.

### Targets / R4 baselines

| Flag | Target | R4 |
|------|--------|----|
| ANALYZE_TABLE | qa_h_multistep | 0/3 |
| CODING_AUTO_TEST | qa_h_code_cli + qa_h_code_debug | 0/3 + 0/3 |
| RESEARCH_PIPELINE | qa_h_research_report | 1/3 |
| PDF_CITATIONS | qa_m_pdf_question | 2/3 |

### Part 1 production guard baselines (flags off)

| Guard | Part1 |
|-------|-------|
| qa_m_organise | 1/3 |
| qa_m_duplicates | 1/3 |
| files_biggest_downloads | 3/3 |
| coding_wordcount | 3/3 |

(Filled after measurement below.)

---

## Part 1 health + bisect

_Pending fill after runs — see also `logs/round6b_part1_bisect.md`._
