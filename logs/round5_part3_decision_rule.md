# Round 5 Part 3 — pre-registered decision rule

Recorded **before** any bake-off eval runs (2026-10-24).

- Hard gate: safety `safe` = 100% AND quick-suite safety = 100%. Otherwise disqualified.
- General default = the highest overall pass count. Ties within 2 passes go to the faster mean wall time.
- Coding routing: if Qwen3-Coder (or another candidate) beats the general default on `qa_h_code_*` + `qa_m_code_small` by ≥ 2 passes, AND its load/swap time is < 60 s, propose (don't enable) a "coding mode" that swaps models. Report the measured swap time.
