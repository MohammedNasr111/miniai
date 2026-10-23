# Trial report 20261022-225349 (Stage 12b-fix)

Model expected: `Qwen3-30B-A3B-GGUF`
Playbook hash (unchanged): `ecbe4e40b344646ff28662fba9c3afba873cd3a899d8465a0b901f262ad3b62c`
Dev tasks: `fresh_firefox, fresh_linux_kernel, fresh_node_lts, fresh_python, web_python_version_plain`
Held-out tasks: `fresh_go, fresh_rust, fresh_postgres, web_mitochondria`
Repeats: dev=3, holdout=2

## Per-variant run counts

| variant | status | models | dev passes/runs | held-out passes/runs | safety | ERROR runs | mean wall s | verdict |
|---|---|---|---:|---:|---|---:|---:|---|
| current | ok | Qwen3-30B-A3B-GGUF | 14/15 | 8/8 | PASS | 0 | 111.453 | (baseline) |
| c1 | ok | Qwen3-30B-A3B-GGUF | 15/15 | 8/8 | PASS | 0 | 119.193 | REJECTED |
| c2 | ok | Qwen3-30B-A3B-GGUF | 15/15 | 8/8 | PASS | 0 | 106.366 | REJECTED |

## ERROR runs (excluded from pass/fail)

- (none)

## Per-task breakdown

| task | variant | passes/runs | suite |
|---|---|---:|---|
| fresh_firefox | current | 3/3 | dev |
| fresh_firefox | c1 | 3/3 | dev |
| fresh_firefox | c2 | 3/3 | dev |
| fresh_go | current | 2/2 | heldout |
| fresh_go | c1 | 2/2 | heldout |
| fresh_go | c2 | 2/2 | heldout |
| fresh_linux_kernel | current | 3/3 | dev |
| fresh_linux_kernel | c1 | 3/3 | dev |
| fresh_linux_kernel | c2 | 3/3 | dev |
| fresh_node_lts | current | 3/3 | dev |
| fresh_node_lts | c1 | 3/3 | dev |
| fresh_node_lts | c2 | 3/3 | dev |
| fresh_postgres | current | 2/2 | heldout |
| fresh_postgres | c1 | 2/2 | heldout |
| fresh_postgres | c2 | 2/2 | heldout |
| fresh_python | current | 2/3 | dev |
| fresh_python | c1 | 3/3 | dev |
| fresh_python | c2 | 3/3 | dev |
| fresh_rust | current | 2/2 | heldout |
| fresh_rust | c1 | 2/2 | heldout |
| fresh_rust | c2 | 2/2 | heldout |
| web_mitochondria | current | 2/2 | heldout |
| web_mitochondria | c1 | 2/2 | heldout |
| web_mitochondria | c2 | 2/2 | heldout |
| web_python_version_plain | current | 3/3 | dev |
| web_python_version_plain | c1 | 3/3 | dev |
| web_python_version_plain | c2 | 3/3 | dev |

## Candidates

### c1 — REJECTED

- instruction: Cross-check factual claims with multiple official sources to ensure accuracy and currency.
- rationale: Ensures answers align with latest verified information from authoritative channels, reducing errors from outdated or non-official data.
- reasons: dev passes 15 < current 14 + 2 (need >= 16)

### c2 — REJECTED

- instruction: Prioritize official documentation and release notes for version-specific details.
- rationale: Directly accessing official resources minimizes reliance on potentially outdated or third-party summaries, improving reliability for technical queries.
- reasons: dev passes 15 < current 14 + 2 (need >= 16)

