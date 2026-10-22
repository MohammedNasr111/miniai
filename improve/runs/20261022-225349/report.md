# Trial report 20261022-225349

Model: `Qwen3-30B-A3B-GGUF`
Playbook hash (unchanged): `ecbe4e40b344646ff28662fba9c3afba873cd3a899d8465a0b901f262ad3b62c`

| variant | dev | held-out | safety | mean wall s | verdict |
|---|---:|---:|---|---:|---|
| current | 100% (4/4) | 100% (4/4) | PASS | 92.896 | (baseline) |
| c1 | 75% (3/4) | 75% (3/4) | PASS | 114.244 | REJECTED |
| c2 | 75% (3/4) | 100% (4/4) | PASS | 91.97 | REJECTED |

## Candidates

### c1 — REJECTED

- instruction: Cross-check factual claims with multiple official sources to ensure accuracy and currency.
- rationale: Ensures answers align with latest verified information from authoritative channels, reducing errors from outdated or non-official data.
- reasons: dev pass rate 0.75 <= current 1.0; held-out pass rate 0.75 < current 1.0; mean wall 114.244 > current×1.2 (111.475)

### c2 — REJECTED

- instruction: Prioritize official documentation and release notes for version-specific details.
- rationale: Directly accessing official resources minimizes reliance on potentially outdated or third-party summaries, improving reliability for technical queries.
- reasons: dev pass rate 0.75 <= current 1.0

