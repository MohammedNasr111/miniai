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
  is 13305 (not 8000). The installer adds a Startup-folder shortcut (LemonadeServer.exe
  --silent), so the server starts at login; it is not a Windows
  service. scripts/agent_loop.py checks /health first and exits with a
  clear message if the server is down.
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
  pages). Timeouts are per-call: 90 s for tool-selection, 450 s for
  synthesis (web_research synthesis measured up to 263 s).
- Structured memory: SQLite. Vector store: LanceDB (embedded, file-based -
  no separate DB server). Embeddings: nomic-embed-text-v1-GGUF served by
  Lemonade's /embeddings endpoint, 768-dim, pre-normalized (cosine and dot
  product are interchangeable). search_knowledge returns `distance`, where
  LOWER means more similar.
- Browser automation: Playwright. General Windows UI control: Windows UI
  Automation first; screenshot/vision only as a fallback of last resort.
- Web research: the model's web tool is web_research (AUTO_ALLOW,
  taints the session). In code, not by model choice: it searches Tavily
  (free tier, no card, key in .env as TAVILY_API_KEY, behind a swappable
  SearchProvider), fetches the top 4 live pages, chunks them, ranks
  passages across pages with local embeddings, and returns the top 6
  (max 3 per page) each with its next chunk appended, plus source URLs,
  inside untrusted-content markers. Verification is done in code because
  live tests showed the model never chose to fetch pages when given only
  search snippets, and answered from stale snippets. Tavily sees queries
  only; pages are fetched locally. fetch_url (CONFIRM) remains for a
  specific URL the user gives: it blocks non-public addresses on every
  redirect hop, caps size (3 MB) and time (30 s), and returns only
  top-ranked chunks. web_search exists as an internal building block and
  is not exposed to the model. Known accepted gap: DNS is resolved
  separately for validation and connection.
- LLM access goes through a provider-swappable interface with a single
  chat() method (tools optional) - local (Lemonade) is default, cloud
  (OpenAI/Anthropic) is optional and explicit. Streaming is deferred until
  a latency-sensitive use case exists.
- Every tool call must route through a single permission-gate middleware
  (security/) — not per-tool checks. Tiers: auto-allow (read/search/web
  search), confirm-first (create/modify files, terminal, memory
  writes, indexing folders, web fetch), always-confirm (delete, install,
  run unknown executables). Session taint: once a tool in
  UNTRUSTED_SOURCE_TOOLS (fetch_url and web_search) succeeds, the session is
  tainted. In a tainted session every CONFIRM/ALWAYS_CONFIRM prompt shows
  a warning banner, and every such action except fetch_url requires
  typing the exact action name - a plain 'yes' is denied. Live testing
  showed the model will attempt injected deletes after a user's 'go
  ahead'; this gate, not the model, is the safety boundary. Accepted
  residual risk: a manipulated model can still ask the user to type the
  action name, so the banner relies on the user.

## Known model limitations (design around, do not rely on the model)
- Qwen3-14B is unreliable at counting/enumeration even with thinking on.
  Exact counts and lists must be computed in code and given to the model
  as facts.
- It may invent plausible reasons for things it does not know (e.g. why
  a permission was denied). Report facts, not guesses.
- Duplicate tool calls are blocked by agent/executor/guard.py: an
  identical mutating call is never re-run or re-prompted in one session;
  an identical read-only call is re-run only if a mutating call has
  succeeded since. Blocked calls still return a matching tool result.
- Web answers depend on what search returns that day. Live fetching,
  4 sources and neighbor expansion reduced but did not eliminate cases
  where no authoritative page is retrieved; a correct answer is not
  guaranteed.
- Quotes the model attributes to sources are not verified against the
  retrieved text (planned for Stage 10 evaluation).
- search_knowledge flags each result's freshness (current / modified
  since indexing / file missing / unknown) using a per-file fingerprint
  recorded at indexing time; it never re-indexes on its own, because
  indexing is CONFIRM-tier. Accepted limitation: a content change that preserves the file's exact
  modification time is reported as current.
- Browser DNS rebinding: requests are checked per host when first seen,
  and Chromium's own local-network protection could not be verified to
  apply; a page that rebinds its domain to a local address might reach
  local services. Mitigated by per-open confirmation and a visible
  browser window.
- A hostile page controls what its own elements do: browser_click
  verifies the clicked element is the one observed (same node, label and
  link), but cannot stop a page from changing its own button's behaviour.
  This is why the agent uses its own browser profile and never the
  user's accounts.
- search_memory is AUTO_ALLOW, so injected content can make the model
  read memories without a prompt; any attempt to send them out through
  browser_open or fetch_url is stopped at the confirmation prompt, which
  shows the full URL.

## Roadmap
Stage 0: environment setup (done)
Stage 1: Lemonade installed + one model running, verified (done)
Stage 2: minimal agent loop (chat only, no tools) (done)
Stage 3: filesystem tools + permission gate (done)
Stage 4: memory (SQLite) (done)
Stage 5: RAG (LanceDB) (done)
Stage 6: web research (done)
Stage 7: browser automation (Playwright) (next)
Stage 8: computer control (UI Automation)
Stage 9: coding agent
Stage 10: evaluation / self-improvement loop

## Not building yet
Voice, vision/screenshot understanding, scheduled tasks, email/calendar
integration, multi-agent orchestration, cloud-fallback routing.
