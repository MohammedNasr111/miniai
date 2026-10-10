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
  Thinking mode (`chat_template_kwargs.enable_thinking`) is PER-CALL, not a
  blanket default: OFF for tool-selection calls (deciding which tool to call
  needs no reasoning), ON for any call where the conversation history already
  contains a tool-role message (i.e. synthesizing/counting/aggregating real
  tool output). Verified in Stage 3 testing: thinking-off correctly listed 18
  directory entries but miscounted them as 15; thinking-on with the identical
  prompt and tool result counted correctly (18) at roughly 8x the wall-clock
  cost. The cost is worth paying only on the synthesis call, not every call.
  NPU/Hybrid path (Qwen3-14B-Hybrid, ryzenai-llm recipe) was
  tested and PARKED: model loads and shows healthy status, but generation
  never completes (proxy and direct-backend timeouts on v1.7.0). Revisit only
  after a Lemonade/AMD driver update, or if GPU-path throughput proves
  insufficient once real tool-calling load is added.
  Context: allocated 16384 tokens (persisted per-model via
  --save-options; benchmarked 2026-10: allocation costs ~1.9 GB RAM vs 4096
  and no speed). Prompt processing runs ~65-117 tok/s and slows as prompts
  grow, so the working target is ~6K prompt tokens per call. Tool results
  must be bounded in code (e.g. return relevant chunks, never whole web
  pages). Timeouts are per-call: 90 s for tool-selection, 300 s for
  synthesis.
- Structured memory: SQLite. Vector store: LanceDB (embedded, file-based -
  no separate DB server). Embeddings: nomic-embed-text-v1-GGUF served by
  Lemonade's /embeddings endpoint, 768-dim, pre-normalized (cosine and dot
  product are interchangeable). search_knowledge returns `distance`, where
  LOWER means more similar.
- Browser automation: Playwright. General Windows UI control: Windows UI
  Automation first; screenshot/vision only as a fallback of last resort.
- Web search: Tavily API (free tier, no card on file, key in .env as
  TAVILY_API_KEY), behind a swappable search-provider interface. Tavily is
  used for search only; pages are fetched and processed locally, so the
  search provider sees queries but not which pages are read. All fetched
  web content is untrusted data and must never be treated as instructions.
- LLM access goes through a provider-swappable interface with a single
  chat() method (tools optional) - local (Lemonade) is default, cloud
  (OpenAI/Anthropic) is optional and explicit. Streaming is deferred until
  a latency-sensitive use case exists.
- Every tool call must route through a single permission-gate middleware
  (security/) — not per-tool checks. Tiers: auto-allow (read/search/web
  search/web fetch), confirm-first (create/modify files, terminal, memory
  writes, indexing folders), always-confirm (delete, install, run unknown
  executables).

## Known model limitations (design around, do not rely on the model)
- Qwen3-14B is unreliable at counting/enumeration even with thinking on.
  Exact counts and lists must be computed in code and given to the model
  as facts.
- It may invent plausible reasons for things it does not know (e.g. why
  a permission was denied). Report facts, not guesses.
- There is currently NO duplicate-tool-call guard; only a 5-round cap and
  a 'Do not retry' message after denials. A guard is planned before web
  tools land.

## Roadmap
Stage 0: environment setup (done)
Stage 1: Lemonade installed + one model running, verified (done)
Stage 2: minimal agent loop (chat only, no tools) (done)
Stage 3: filesystem tools + permission gate (done)
Stage 4: memory (SQLite) (done)
Stage 5: RAG (LanceDB) (done)
Stage 6: web research (current stage)
Stage 7: browser automation (Playwright)
Stage 8: computer control (UI Automation)
Stage 9: coding agent
Stage 10: evaluation / self-improvement loop

## Not building yet
Voice, vision/screenshot understanding, scheduled tasks, email/calendar
integration, multi-agent orchestration, cloud-fallback routing.
