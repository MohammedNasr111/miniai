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
- Tests never touch real data: every test that writes uses temporary
  stores via `tests/support.py` and refuses to run against the real paths.
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
  Thinking policy (`settings.THINKING_POLICY`, overridable via
  `MINIAI_THINKING_POLICY`): default **`two_pass`** — every model call runs
  with thinking off first; if the response has tool calls, use it; if it is
  a final answer, discard it (transcript `discarded: true`) and repeat the
  same call with thinking on and the synthesis timeout. Alternative
  `on_after_tools` keeps the older rule (off until a tool result is in
  history, then on). Part C comparison (2026-10-17): Wikipedia search wall
  509 s / 5 calls (`on_after_tools`) vs 424 s / 9 calls (`two_pass`, three
  discarded finals); research+create_file 226 s / 3 vs 138 s / 4; directory
  count 239 s / 2 vs 317 s / 3 — both policies answered correctly, and
  `two_pass` often produces a usable tool plan without paying thinking cost
  up front, so it is the default. Browser live comparison (2026-10-17,
  Wikipedia W×3 + python.org Downloads P×2 under each policy): both scored
  **3/5** completed real steps; keep **`two_pass`** for speed. Verified
  earlier: thinking-off correctly listed 18 directory entries but
  miscounted them as 15; thinking-on with the identical prompt and tool
  result counted correctly (18).
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
  UNTRUSTED_SOURCE_TOOLS (fetch_url, web_research, browser_open,
  browser_observe, browser_click, browser_type) succeeds, the session is
  tainted. In a tainted session every CONFIRM/ALWAYS_CONFIRM prompt shows
  a warning banner, and every such action except those in
  TAINT_YESNO_ACTIONS (fetch_url, browser_open, browser_click) requires
  typing the exact action name - a plain 'yes' is denied. Exception
  (URL provenance): fetch_url and browser_open still require the action
  name when the URL is not in the session's known set — URLs from the
  user's messages, hrefs and form actions in browser observations, source
  URLs from web_research, and final URLs after navigation or fetch.
  Unknown (model-constructed) URLs prompt: "This URL was not given by you
  or supplied by a page or search result - the model constructed it.
  Typed confirmation required." Known URLs and untainted sessions keep
  yes/no. browser_click stays yes/no. browser_type is deliberately not in
  TAINT_YESNO_ACTIONS. `describe_url` / `carries_data` remain for display
  only. Live testing showed the model will attempt injected deletes after
  a user's 'go ahead'; this gate, not the model, is the safety boundary.
  Accepted residual risk: a manipulated model can still ask the user to
  type the action name, so the banner relies on the user.
- Browser tools: browser_open / browser_observe / browser_click /
  browser_type. Permission prompts for fetch_url, browser_open, and
  browser_click use describe_url so percent-encoded path/query/fragment
  data appears decoded (path only when decoding changes it; each query
  parameter; fragment when present). Submit controls also show
  "Submits a form to: <describe_url(action)> (method GET|POST)".
  browser_type fills a textbox from the latest observation after the same
  node/role/name re-check as click; it refuses without prompting for
  password fields, autocomplete containing "password" or starting with
  "cc-", and name/id matching /(pass|pwd|card|cvv|cvc|iban)/i.   Optional
  `submit=true` presses Enter after fill (prompt shows the form's
  action/method from observe, or that the field is not in a form); textbox
  observe capture includes the enclosing form's submission destination the
  same way submit buttons do. Element handles are captured in the same page
  evaluation that assigns refs (atomic capture). `observe()` page text prefers
  `extract_text` / trafilatura ("from article text"), else scope `innerText`
  ("from main content" / "from whole page"); always shows a start section
  (up to 1500 or 3000 chars) and, when a non-stop `looking_for` word matches
  after character 1500, an around-match excerpt from the nearest sentence
  start.
- Interactive chat (`python -m scripts.chat`): one session keeps one history,
  one CallGuard, one Transcript, and one browser window across turns. Taint
  and denials never reset between turns (only at start and on `/new`). Chat
  replies such as "yes, go ahead" are never approvals — only the permission
  gate's own prompts approve actions. Before each model call, tool results
  from earlier user turns are replaced with a short omitted note except the
  single most recent browser observation (kept full); the transcript retains
  originals. `/new` closes the browser, clears taint/guard, and starts a
  fresh history; `/exit` ends the session; `/status` shows taint sources,
  turn count, and last prompt token count. Ctrl+C mid-turn cancels that
  turn and truncates history to its pre-turn length.

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
- A hostile page controls what its own elements do: browser_click and
  browser_type verify the target is the one observed (same node, label
  and link/form metadata), but cannot stop a page from changing its own
  button's behaviour. This is why the agent uses its own browser profile
  and never the user's accounts.
- Elements inside iframes are not visible to the agent.
- A page's own scripts can send typed text or redirect a form submission
  anywhere; the prompts show the declared destination, not what scripts
  may do.
- search_memory is AUTO_ALLOW, so injected content can make the model
  read memories without a prompt; any attempt to send them out through
  browser_open, fetch_url, or browser_type is stopped at the confirmation
  prompt (decoded URL or the exact text to type).

## Roadmap
Stage 0: environment setup (done)
Stage 1: Lemonade installed + one model running, verified (done)
Stage 2: minimal agent loop (chat only, no tools) (done)
Stage 3: filesystem tools + permission gate (done)
Stage 4: memory (SQLite) (done)
Stage 5: RAG (LanceDB) (done)
Stage 6: web research (done)
Stage 7: browser automation (Playwright) (done)
Stage 7.5: interactive chat (done)
Stage 8: computer control (UI Automation)
Stage 9: coding agent
Stage 10: evaluation / self-improvement loop

## Not building yet
Voice, vision/screenshot understanding, scheduled tasks, email/calendar
integration, multi-agent orchestration, cloud-fallback routing.
