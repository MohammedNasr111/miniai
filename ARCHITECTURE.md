# MiniAI — Personal Local AI Agent

## Hardware
- AMD Ryzen AI 9 HX 370 (12C/24T), Radeon 890M iGPU (gfx1150, RDNA 3.5),
  AMD XDNA NPU, 1TB SSD, Windows 11.
- 32GB DDR5-5600 installed, but ~23.6GB usable by the OS — roughly 8GB is
  reserved for the iGPU below the OS level and never appears as system RAM.
  Practical model-size budget: keep on-disk model size under ~14GB with real
  caution above that.
- Memory behaves like a unified-memory system (GPU has no dedicated VRAM) —
  closer to Apple Silicon than a discrete-GPU PC.

## Core decisions (do not change without the architect's sign-off)
- Local inference runtime: **Lemonade** (AMD's OpenAI-compatible local
  server), not Ollama. Ollama's ROCm backend does not officially support
  this GPU (gfx1150); Lemonade auto-selects NPU/iGPU/CPU backends and is
  purpose-built for this hardware tier.
  Install: `winget install --id AMD.LemonadeServer -e --source winget`.
  The CLI command is `lemonade` (not `lemonade-server`). The default port
  is 13305 (not 8000). The installer runs the server automatically as a
  background service — no manual `lemonade serve` step is needed.
- Default model: **Qwen3-14B-GGUF** (llamacpp/vulkan recipe, ~8GB on disk).
  Thinking mode (`chat_template_kwargs.enable_thinking`) is OFF by default in
  the provider layer — verified in benchmarking that disabling it cuts
  wall-clock time ~24x for simple responses with no token-rate change and no
  quality loss. NPU/Hybrid path (Qwen3-14B-Hybrid, ryzenai-llm recipe) was
  tested and PARKED: model loads and shows healthy status, but generation
  never completes (proxy and direct-backend timeouts on v1.7.0). Revisit only
  after a Lemonade/AMD driver update, or if GPU-path throughput proves
  insufficient once real tool-calling load is added.
- Structured memory: SQLite. Semantic/vector memory: LanceDB or Chroma
  (embedded, file-based — no separate DB server to run).
- Browser automation: Playwright. General Windows UI control: Windows UI
  Automation first; screenshot/vision only as a fallback of last resort.
- LLM access goes through a provider-swappable interface
  (generate/chat/stream/tool_call) — local (Lemonade) is default, cloud
  (OpenAI/Anthropic) is optional and explicit.
- Every tool call must route through a single permission-gate middleware
  (security/) — not per-tool checks. Tiers: auto-allow (read/search/web
  search), confirm-first (create/modify files, terminal), always-confirm
  (delete, install, run unknown executables).

## Roadmap
Stage 0: environment setup (current stage)
Stage 1: Lemonade installed + one model running, verified
Stage 2: minimal agent loop (chat only, no tools)
Stage 3: filesystem tools + permission gate
Stage 4: memory (SQLite)
Stage 5: RAG (LanceDB)
Stage 6: web research
Stage 7: browser automation (Playwright)
Stage 8: computer control (UI Automation)
Stage 9: coding agent
Stage 10: evaluation / self-improvement loop

## Not building yet
Voice, vision/screenshot understanding, scheduled tasks, email/calendar
integration, multi-agent orchestration, cloud-fallback routing.
