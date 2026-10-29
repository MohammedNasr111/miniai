# Round 9 — bandwidth probe

Source JSON: `C:/Users/mohdc/OneDrive/Desktop/miniai/logs/round9_bandwidth.json`

| Model | mean tok/s | file GB | bytes/token (assumed) | mean effective GB/s | vs 44.8 GB/s |
|---|---:|---:|---:|---:|---:|
| Qwen3-14B-GGUF | 3.988 | 7.956 | 7.956 GB | 31.727 | 71% |
| Qwen3-30B-A3B-GGUF | 16.066 | 16.186 | 1.751 GB | 28.137 | 63% |

With normal apps still open (Cursor.exe, Cursor.exe, llama-server.exe, claude.exe, MsMpEng.exe, claude.exe, Cursor.exe, explorer.exe; free RAM 4.086 GB of 23.618 GB), a 512-token generation was timed 3× on each installed GGUF under production llama.cpp options (ctx 16384, `--n-gpu-layers 99 -ctk q8_0 -ctv q8_0 -fa on --parallel 1`). Effective bandwidth is tok/s × assumed bytes/token; one DDR5-5600 channel is 44.8 GB/s. 14B dense: bytes/token ≈ GGUF file size (full weight read per token). 30B-A3B MoE: bytes/token ≈ file_size × (3.3/30.5≈0.1082). This under-states shared dense/attention traffic; treat as a lower bound on bytes moved per token. This note does not recommend a purchase.
