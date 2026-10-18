# MiniAI — Personal Local AI Agent

## Hardware
- AMD Ryzen AI 9 HX 370 (12C/24T), Radeon 890M iGPU (gfx1150, RDNA 3.5),
  AMD XDNA NPU, 1TB SSD, Windows 11.
- 32GB DDR5-5600 installed, but ~23.6GB usable by the OS — roughly 8GB is
  reserved for the iGPU below the OS level and never appears as system RAM.
  Practical model-size budget: model files up to ~18 GB are workable; leave
  ~4 GB free. Startup warns when free RAM is under 4 GB.
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
- Default model: **Qwen3-30B-A3B-GGUF** (MoE, llamacpp/vulkan, ~17.4 GB on
  disk, ctx 16384, ~19.8/23.6 GB RAM when loaded). Selected after a local
  speed round (2026-10-18, `logs/local_speed_20261018-125533.json`): equal
  correctness on Test A×2 / Test B / root-count vs Qwen3-14B and Qwen3-8B,
  with ~3× lower wall clock on the 30B-A3B. Reason: same answers, much
  faster. **Qwen3-14B-GGUF** is kept as fallback via `MINIAI_MODEL`.
  Measured wall seconds (correct=T/F):

  | Run | Qwen3-14B | Qwen3-8B | Qwen3-30B-A3B |
  |---|---|---|---|
  | Test A x1 | T / 209.3 | T / 223.4 | T / 68.3 |
  | Test A x2 | T / 220.9 | T / 154.8 | T / 58.9 |
  | Test B | T / 226.0 | T / 108.9 | T / 80.0 |
  | root-count | T / 160.2 | T / 58.7 | T / 34.8 |
  | ATP chat | F / 554.4 | F / 533.4 | F / 252.0 |
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
  --save-options). Prompt processing slows as prompts grow, so the working
  target is ~6K prompt tokens per call. Tool results must be bounded in
  code (e.g. return relevant chunks, never whole web pages). Timeouts are
  per-call: 90 s for tool-selection (adaptive first-pass under two_pass),
  450 s for synthesis.
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
- File changes are recoverable by design: deletes go to the Recycle Bin,
  overwrites keep a backup in %LOCALAPPDATA%\MiniAI\backups, and the agent
  cannot modify its own folder or settings.
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
  from earlier user turns keep the most recent result of each tool name in
  full; older ones are replaced with a short omitted note (call the tool
  again if needed). Every tool result's full text is also kept in a
  per-session evidence store (cleared on `/new`) before compression. After
  each final answer, quoted passages of 25+ characters are checked
  word-for-word against that evidence; if any quote is missing, a note is
  appended telling the user to treat it as a paraphrase, and a
  `quote_check` transcript event is logged. Within one tool_calls batch,
  after a page-changing action (`browser_open`, `browser_click`, or
  `browser_type` with `submit=true`) has run, later `browser_click` /
  `browser_type` calls in that batch are skipped (stale element refs).
  `/new` closes the browser, clears taint/guard/evidence, and starts a
  fresh history; `/exit` ends the session; `/status` shows taint sources,
  turn count, and last prompt token count. Ctrl+C mid-turn cancels that
  turn and truncates history to its pre-turn length (approved actions are
  not undone).

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
- Quotes are checked word-for-word against retrieved text; paraphrases
  presented as quotes are flagged, not corrected.
- Multi-step browsing with the 14B model is unreliable: it often plans
  several browser steps before seeing the page. Guessed element numbers
  are skipped and reported back, which usually lets it recover in the
  next step.
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
- Tabbed apps (Notepad, browsers) show one document at a time; MiniAI acts
  only on the active tab and refuses if it changed (window title check
  after the last `desktop_read_window`).

## Stage 8a — read-only desktop observation (done)
- Library: **uiautomation==2.0.29** (pinned). Chosen over pywinauto for a
  smaller dependency surface and direct `ControlFromHandle` / tree walk
  without Win32-backend indirection.
- Tools (both AUTO_ALLOW; both in `UNTRUSTED_SOURCE_TOOLS` — reading an app
  taints the session):
  - `desktop_list_windows` — visible top-level windows as `[wN] <exe> -
    <title>` (title sanitized/one_line, max 120), wrapped in untrusted
    markers (titles are untrusted). Blocked apps omitted. Refs renumber
    on each list.
  - `desktop_read_window(window, looking_for?)` — UIA tree walk in a worker
    thread joined at 6 s (partial results + "(truncated: the app did not
    respond in time)" on timeout). Max depth 12 / 2000 nodes. Output
    wrapped with the same untrusted PREAMBLE/BEGIN/END as web. Up to 60
    elements and 3000 chars of text. Keeps per-element control + snapshot
    (type, name, AutomationId, RuntimeId) for 8b actions.
- Per-app trust (`security/app_trust.py`): file
  `%LOCALAPPDATA%\MiniAI\trusted_apps.json` keyed by lowercase exe name
  (protected path — create/write/delete refuse it). Prompt via
  `gate.prompt_app_read` (title sanitized/one_line/120; browser exes add a
  logged-in-sites warning): type `session` / `always` / refuse. Session
  grants and refusals clear on `reset_session()`.
- Blocked executables (never listed, never read, no prompt): keepass.exe,
  keepassxc.exe, 1password.exe, bitwarden.exe, lastpass.exe,
  securityhealthui.exe, systemsettings.exe, consent.exe,
  credentialuibroker.exe, mmc.exe, regedit.exe, taskmgr.exe. Also any
  window whose title contains "password manager" (case-insensitive).
- Password fields (`IsPassword`): shown as `[password field - not read]`;
  value never read.
- Startup low-memory warning uses `settings.MODEL_NEEDED_RAM_GB` (18).

## Stage 8b — desktop actions (done)
- `desktop_begin_task(window, goal)` CONFIRM: one-turn grant for that exe
  only (prompt shows exe, goal, allowed vs always-ask lists; typed name
  when tainted). Cleared after each `run_tool_rounds` (end of user turn)
  and on `reset_session`. Without a grant, press/set_text return
  "Call desktop_begin_task first."
- `desktop_press(element)` / `desktop_set_text(element, text)` /
  `desktop_insert_text(element, text, position)`: CONFIRM tier for the
  duplicate-call guard; all in `UNTRUSTED_SOURCE_TOOLS`. Re-verify snapshot
  before acting. Press uses Invoke → Toggle → SelectionItem (never mouse).
  **Insert vs replace:** prefer `desktop_insert_text` (`start`/`end`) when
  adding text — it reads the full current field value (ValuePattern, with
  Win32 WM_GETTEXT when UIA truncates), concatenates, writes, and verifies;
  on mismatch it restores the original. `desktop_set_text` replaces the
  whole field; if the field is already non-empty it always prompts even
  with a grant: "Replace the existing text in <exe> field \"<name>\"? It
  currently has <N> characters; they will be replaced by <M> characters."
  (typed name when tainted). Same password/read-only refusals and 500-char
  piece limit as each other. Results include a fresh window read.
- **Tab/title check:** `desktop_read_window` stores the window title; every
  act tool re-reads it first and refuses if it changed: "The window now
  shows a different document or tab (title changed). Read the window again."
- Always-ask (extra CONFIRM even with grant): element name whole-word match
  on send/delete/remove/submit/pay/buy/purchase/discard/don't save/close/
  exit/uninstall/erase/reset/sign out/publish/post/share/format, or any
  element inside a dialog/modal window.
- ACT_BLOCKED (read may be allowed; acting refused without prompt): the
  five browsers, cmd/powershell/pwsh/WindowsTerminal/wt/conhost, cursor,
  code, explorer, plus all BLOCKED_EXECUTABLES. Message names browser
  tools / file tools / "not yet supported" as appropriate.
- Emergency stop (`security/user_input_watch.py`): WH_MOUSE_LL /
  WH_KEYBOARD_LL while a grant is active. Physical events (no
  LLMHF_INJECTED / LLKHF_INJECTED) set a flag; the next act asks
  "You used the mouse or keyboard. Continue the task? (yes/no)" — no ends
  the grant. Hooks uninstalled when the grant ends (and via atexit).

## Stage 8 plan (remaining)
Further computer control beyond 8a/8b as needed (broader app support,
richer patterns).

## Stage 9a — isolated code runner (done)
- **Workspace:** `%USERPROFILE%\AppData\LocalLow\MiniAI\workspace` (writable at
  low integrity). MiniAI versions it with git (`author MiniAI`) after every
  `run_code` and after create/write/delete under the workspace.
- **Runner venv:** `%LOCALAPPDATA%\MiniAI\runner-venv` (medium integrity). On
  Windows, `Scripts\python.exe` is a launcher that re-execs the base
  interpreter; Job Object `ACTIVE_PROCESS=1` forbids that child, so MiniAI
  copies a real `python.exe` + DLLs to `runner-venv\runner-bin\` and launches
  that path (firewall rule targets the same file). Stdlib via `PYTHONHOME`
  from `pyvenv.cfg` `home`; venv `site-packages` on `PYTHONPATH`.
- **`run_code(code)`** CONFIRM (typed name when tainted): shows numbered
  code, limits, and firewall status (`INSTALLED` / `NOT INSTALLED`). Runs via
  `tools/code/runner.py`: write `run_<stamp>.py`, CreateProcessAsUser at Low
  Mandatory Level (`S-1-16-4096`), Job Object with `KILL_ON_JOB_CLOSE`,
  active-process limit 1, process memory 2 GB, wall timeout (default 60s).
  Minimal env (no `.env` / `TAVILY_API_KEY`). stdout/stderr each capped at
  20,000 characters with a truncation note. Low-IL launch failure **refuses**
  (never falls back to a normal launch). Output wrapped in untrusted code
  markers; `run_code` is in `UNTRUSTED_SOURCE_TOOLS`.
- **`workspace_history()`** AUTO_ALLOW (last 20 commits);
  **`workspace_restore(commit)`** CONFIRM (lists files that will change;
  `git checkout <commit> -- .` then a new MiniAI commit — history kept).
- **Firewall:** user runs `scripts/setup_runner_firewall.ps1` once as admin
  (Cursor does not elevate it): one outbound block rule named
  `MiniAI code runner - block internet` for `runner-bin\python.exe` only;
  `--remove` supported. Runner reports rule status with `Get-NetFirewallRule`
  (read does not need admin).
- **Residual risks:** low-IL code can still **read** the user's files (MIC is
  no-write-up, not no-read-up); program output returns to the local model
  (hence untrusted markers + taint); network blocking depends on the optional
  firewall rule.

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
Stage 8: computer control (in progress - 8a read-only done, 8b actions done)
Stage 9: coding agent (in progress - 9a isolated runner done)
Stage 10: evaluation / self-improvement loop

## Not building yet
Voice, vision/screenshot understanding, scheduled tasks, email/calendar
integration, multi-agent orchestration, cloud-fallback routing.
