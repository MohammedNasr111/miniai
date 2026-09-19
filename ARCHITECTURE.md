# MiniAI — Personal Local AI Agent

## Hardware
- AMD Ryzen AI 9 HX 370 (12C/24T), Radeon 890M iGPU (gfx1150, RDNA 3.5),
  32GB DDR5-5600 shared RAM/VRAM, AMD XDNA NPU, 1TB SSD, Windows 11.
- Memory behaves like a unified-memory system (GPU has no dedicated VRAM) —
  closer to Apple Silicon than a discrete-GPU PC.

## Core decisions (do not change without the architect's sign-off)
- Local inference runtime: **Lemonade** (AMD's OpenAI-compatible local
  server), not Ollama. Ollama's ROCm backend does not officially support
  this GPU (gfx1150); Lemonade auto-selects NPU/iGPU/CPU backends and is
  purpose-built for this hardware tier.
- Starting model: **Qwen3 14B** (tool-calling, /think mode). Coding-specific
  work later uses Qwen3-Coder 14B or Devstral. Do not jump to 30B+ models
  before the 14B loop is proven working.
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
