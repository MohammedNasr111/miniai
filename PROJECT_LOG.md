# Project Log

Append one dated entry here after every completed task, in the form:
## YYYY-MM-DD — <task name>
- What was done
- Any decisions made or deviations from ARCHITECTURE.md, with reason
- Current state / what's verified working

## 2026-09-18 — Initialize project skeleton
- Created the Stage 0 folder tree (agent/, llm/, memory/, tools/, research/, security/, config/, tests/, logs/, scripts/, docs/) with `.gitkeep` in each directory; added `.gitignore` (Python/Windows, including `.venv/`, `__pycache__/`, `.env`, logs, sqlite, and local vector-db files), empty `.env.example`, `ARCHITECTURE.md` (verbatim source of truth), and this log.
- No deviations from ARCHITECTURE.md. `git init` was not run: Git is not installed and is not on PATH. Python/`py` are also not available. Nothing was installed (per setup-only scope).
- Current state: empty skeleton only. Verified working: `winget v1.29.380`. Not verified: Git, Python, Lemonade, any model. Still Stage 0.

## 2026-09-20 — Install Git and Python, initialize git repo
- Installed Git via `winget install --id Git.Git -e --source winget` (Git 2.55.0.3). Installed Python 3.12 via `winget install --id Python.Python.3.12 -e --source winget` (Python 3.12.10). After a new shell PATH refresh, verified: `git version 2.55.0.windows.3`, `Python 3.12.10`, `pip 25.0.1 from C:\Users\mohdc\AppData\Local\Programs\Python\Python312\Lib\site-packages\pip (python 3.12)`. Ran `git init` (empty repo at `.git/`) and `git add .` (skeleton files staged). `git commit` did not succeed: Git has no author identity (`fatal: unable to auto-detect email address (got 'mohdc@MiniBeast.(none)')`). Did not run `git config` to set name/email.
- No deviations from ARCHITECTURE.md.
- Current state: Git and Python 3.12 are installed and on PATH in a new shell. Repo is initialized with staged Stage 0 files but has no commits yet. Still Stage 0. Next: set Git user.name / user.email, then create the first commit.

## 2026-09-20 — Configure local git identity and first commit
- Set repo-local identity only (`git config user.name` / `user.email`, not `--global`): MohammedNasr111 / mohdcool.2003@gmail.com. Retried `git commit -m "Stage 0: project skeleton, ARCHITECTURE.md, PROJECT_LOG.md"`. Commit succeeded: `0afa4c2`.
- No deviations from ARCHITECTURE.md.
- Current state: first commit is on `master` (`0afa4c2`). Git identity is local to this repo. Still Stage 0.

## 2026-09-22 — Stage 1: Lemonade Server + Qwen3-14B running
- Installed Lemonade Server 11.9.0 via `winget install --id AMD.LemonadeServer -e --source winget` (package `lemonade-server-minimal.msi`). Pulled `Qwen3-14B-GGUF` (`unsloth/Qwen3-14B-GGUF:Q4_0`): 8147.2 MB downloaded in 6 min 58 s (~22-52 MB/s), 7.96 GB on disk at `C:\Users\mohdc\.cache\huggingface\hub\models--unsloth--Qwen3-14B-GGUF`. Health check `GET http://localhost:13305/api/v1/health` returned `"status":"ok"`, version 11.9.0. One chat request to `/api/v1/chat/completions` returned, verbatim: "I am running locally on your device." (plus a `reasoning_content` field — Qwen3 /think mode is on by default). 142 completion tokens at 3.86 tok/s; prompt 29.1 tok/s.
- Deviations from the task script, none affecting ARCHITECTURE.md decisions: (1) v11.9.0 ships no `lemonade-server` executable — the CLI is `lemonade.exe` (`lemonade --version`, `lemonade status`, `lemonade pull`), already on the user PATH at `%LOCALAPPDATA%\lemonade_server\bin\`. (2) The default port is **13305**, not 8000; nothing listens on 8000 (curl exit 7). (3) No `lemonade serve` was needed — the MSI installs a server that was already running, and it auto-loaded the model on first request.
- Backend note for the architect: the model loaded on `device=gpu` via **llamacpp/vulkan**, ctx 4096 — not the NPU. Lemonade detected "NPU hardware: Yes" but the NPU path needs the separate `Qwen3-14B-Hybrid` model (16.50 GB, `ryzenai-llm` recipe). 3.86 tok/s on Vulkan is slow for interactive use; worth deciding later whether to switch to the Hybrid build. No change made without sign-off.
- Current state: Stage 1 complete and verified end-to-end — Lemonade 11.9.0 running on port 13305, Qwen3-14B-GGUF downloaded, loaded, and answering chat requests. Next: Stage 2, minimal agent loop (chat only, no tools).

## 2026-09-23 — Benchmark: thinking-mode off (Test A) vs NPU Hybrid build (Test B)
- Corrected the Lemonade bullet in ARCHITECTURE.md: CLI is `lemonade` (not `lemonade-server`), default port 13305 (not 8000), installer runs the server as a background service (no manual `serve`), install command recorded.
- Ran two experiments against the Stage 1 baseline. Same prompt in all three ("Reply with exactly one sentence confirming you are running locally."), same endpoint `POST http://localhost:13305/api/v1/chat/completions`.

| | Baseline | Test A | Test B |
|---|---|---|---|
| Model | Qwen3-14B-GGUF | Qwen3-14B-GGUF | Qwen3-14B-Hybrid |
| Device / recipe | gpu / llamacpp (vulkan) | gpu / llamacpp (vulkan) | npu / ryzenai-llm |
| Thinking mode | on | off | off |
| Completion tokens | 142 | 9 | none produced |
| Tokens/sec | 3.86 | 3.96 | n/a |
| Wall clock | 79.5 s | 3.26 s | timed out (10m00s, 10m22s, 27m+) |
| `reasoning_content` | present (~600 chars) | absent | n/a |
| Inference proc RAM (private) | 9.10 GB | 9.12 GB | 17.69 GB |
| System RAM in use | 16.11 / 23.62 GB | 16.16 / 23.62 GB | peaked 23.44 / 23.62 GB |

- **Test A result**: `"chat_template_kwargs": {"enable_thinking": false}` works and `reasoning_content` disappears entirely. Token *rate* is unchanged (~3.9 tok/s — that is a hard floor of the Vulkan backend), but the token *count* drops 142 -> 9, so wall-clock falls from 79.5 s to ~3 s. Reproduced twice (3.96 and 3.895 tok/s). This is the single biggest latency win available right now and costs nothing.
- **Test B result: FAILED — the NPU never produced a completion.** The model registers and loads on the NPU correctly, but inference never returns. Three attempts: two through Lemonade (10m00s and 10m22s, each ending in `{"error":{"message":"Network error: CURL error: Timeout was reached","type":"network_error"}}` from Lemonade's internal 600 s proxy timeout) and one sent directly to the RyzenAI backend on port 8001 bypassing Lemonade, capped at `max_tokens: 32`, killed after 27 minutes with no response. `ryzenai-server` burned ~1 CPU core continuously (1,523 CPU-seconds) the whole time while its working set collapsed from 11.88 GB to 2.48 GB, and Windows GPU/NPU engine counters showed no engine activity attributable to that PID.
- NPU *was* engaged at load/registration level — this is not a misconfiguration. `lemonade status` reported `Qwen3-14B-Hybrid  llm  npu  ryzenai-llm  4096  ready  amd/Qwen3-14B-onnx-ryzenai-1.7-hybrid`, and the backend's own health endpoint returned `"execution_mode": "hybrid"`, `"ryzenai_version": "1.7.0"`, `"status": "ok"`. Exact server log lines: `[Info] (ryzenai-server Server) Installing ryzenai-server.exe (version: v1.7.0)` / `[Info] (WrappedServer) RyzenAI-Server is ready!` / `[Info] (RyzenAI) Model loaded on port 8001`. The failure is in generation, not in backend selection.
- **Hardware correction for ARCHITECTURE.md (needs architect sign-off before editing)**: the doc says 32GB shared RAM/VRAM. Windows reports `TotalPhysicalMemory = 23.62 GB` usable — a 32 GB Kingston DDR5-5600 module is installed, but ~8 GB is carved out for the iGPU below the OS level, so it never appears as system RAM. Lemonade's own log incorrectly assumes "System RAM: 32.0 GB (max model size: 25.6 GB)", which is why it was willing to load a 17.7 GB model. On the first Test B attempt this filled RAM to 23.44/23.62 GB and paged the model to disk; the retry with 15.5 GB free did not thrash yet still failed, so memory pressure is an aggravating factor, not the root cause.
- Model sizes: Qwen3-14B-Hybrid downloaded 15.4 GB across 17 files in 7 min 22.8 s (~55 MB/s), 15.36 GB on disk. Qwen3-14B-GGUF remains 7.96 GB on disk.
- Per instructions, **no default was changed**. Hybrid was unloaded, `ryzenai-server` stopped, and Qwen3-14B-GGUF was reloaded and re-verified working (9 tokens, 3.895 tok/s, 2.56 s). The 15.36 GB Hybrid download is still on disk and can be deleted with `lemonade delete Qwen3-14B-Hybrid` if the architect rules it out.
- Current state: unchanged from Stage 1 — Lemonade 11.9.0 on port 13305 with Qwen3-14B-GGUF loaded on Vulkan/GPU, answering requests. Awaiting architect's decision on (a) making `enable_thinking: false` the default, (b) whether to keep pursuing the NPU path, and (c) the 23.62 GB RAM correction to ARCHITECTURE.md.

## 2026-09-26 — Stage 1 decisions finalized in ARCHITECTURE.md; Hybrid deleted
- Architect signed off on all three open decisions. Updated ARCHITECTURE.md: hardware RAM line now records 32GB installed / ~23.6GB OS-usable with the ~8GB iGPU reservation and a "keep on-disk model size under ~14GB" budget; the "Starting model" bullet is replaced by a "Default model" bullet naming Qwen3-14B-GGUF (llamacpp/vulkan, ~8GB) with `enable_thinking` OFF by default in the provider layer, and the NPU/Hybrid path formally PARKED pending a Lemonade/AMD driver update or GPU-path throughput proving insufficient under real tool-calling load.
- Deleted Qwen3-14B-Hybrid via `lemonade delete Qwen3-14B-Hybrid`, freeing 15.36 GB (C: 779.41 GB -> 794.77 GB free). `lemonade list --downloaded` now shows only Qwen3-14B-GGUF (7.96 GB).
- No deviations. No model or config defaults were changed beyond the doc edits; the `enable_thinking: false` default is recorded as a decision for the provider layer, which does not exist yet (Stage 2).
- Current state: verified working — Lemonade 11.9.0 on port 13305, `Qwen3-14B-GGUF  llm  gpu  llamacpp  4096  ready`, one chat request returned "I am running locally on your device." in 2.42 s (9 completion tokens, 4.04 tok/s, no `reasoning_content`). Note the server idle-unloads the model, so Stage 2's provider layer must handle on-demand load (first-request latency ~20 s). Next: Stage 2, minimal agent loop (chat only, no tools).
