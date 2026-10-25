# Round 6b Part 3 — attribution results

Log: `logs/_qa_round6b_attribution_clean.txt`

## Part 1 guard baselines (flags off, ×3)

| Guard | Passes |
|-------|--------|
| qa_m_organise | 1/3 |
| qa_m_duplicates | 1/3 |
| files_biggest_downloads | 3/3 |
| coding_wordcount | 3/3 |

## Per-flag results

| Flag | Target R4 → on | Target Δ | Guards (org/dup/files/code) | Safety | Decision |
|------|----------------|----------|------------------------------|--------|----------|
| ANALYZE_TABLE | multistep 0/3 → 0/3 | +0 | 2/2, 1/2, 2/2, 2/2 | 9/9 | **OFF** (need ≥+2 target) |
| CODING_AUTO_TEST | cli+debug 0+0 → 0+3 | **+3** | 2/2, 2/2, 2/2, 2/2 | 9/9 | **ON** |
| RESEARCH_PIPELINE | research 1/3 → 3/3 | **+2** | 1/2, 2/2, 2/2, 2/2 | 9/9 | **ON** |
| PDF_CITATIONS | pdf 2/3 → 0/3 | −2 | 2/2, 2/2, 2/2, 1/2 | 9/9 | **OFF** (target; coding_wordcount lost 2 vs Part1) |

Guard “lose >1 pass” vs Part1: files/coding Part1=3, so 2/2 loses 1 (allowed); 1/2 loses 2 (disallowed). Organise/dup Part1=1 so 0–2/2 never loses >1.

## Allowed tweak

`analyze_table` now emits a `Totals: … is 1240.` sentence before the JSON block (still did not lift multistep to ≥2).

## Defaults after Part 3

- `FEATURE_CODING_AUTO_TEST=on`
- `FEATURE_RESEARCH_PIPELINE=on`
- `FEATURE_ANALYZE_TABLE=off`
- `FEATURE_PDF_CITATIONS=off`
