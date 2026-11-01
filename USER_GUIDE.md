# MiniAI user guide (for James)

Plain English for daily use. Deeper design lives in [ARCHITECTURE.md](ARCHITECTURE.md). Handover notes for whoever picks the project up next: [docs/HANDOVER.md](docs/HANDOVER.md).

## Starting MiniAI

1. Lemonade Server should already be running (it usually starts at login). The chat model is **Qwen3-30B-A3B-GGUF**.
2. From the MiniAI folder, start the desktop app:

```text
.venv\Scripts\pythonw.exe -m app
```

Or use the terminal chat if you prefer:

```text
.venv\Scripts\python.exe -m scripts.chat
```

3. Type a request and send it. MiniAI will ask before risky actions (writes, deletes, installs, desktop control, some fetches).

## What the status chip means

The chip near the top of the window is the live pulse of the current turn:

- **Warming up…** — starting the turn / connecting to the model.
- **Thinking…** — the model is doing a hidden draft or a thinking pass (you may not see answer text yet).
- **Writing…** — visible answer text is streaming.
- **Reading… / tool name** — a tool is running (for example listing a folder or fetching a page).
- **Waiting for you…** — an approval prompt is open.
- **Checking…** — honesty / coverage guards are running before the final answer sticks.

Elapsed seconds sit next to the label. Click the chip for a short System popover (model health, free RAM, Reload model).

## Settings (gear, or Ctrl+,)

Open **Settings** from the gear or **Ctrl+,**.

- **Gemini** — optional cloud helper for some hard turns. If a key is set, only the snippets MiniAI chooses leave this PC; your whole disk is not uploaded. Rows that left this PC show up in the Footprint.
- **Planner / Groq** — optional short planning step (default **off**). Same idea: only a compact plan prompt would go to Groq if you turn it on and provide a key. Local tools and files stay local.
- Keys live in `.env` on this machine. Never paste them into chat or into screenshots.

What stays local by default: the main chat model (Lemonade), file tools, memory, knowledge search, browser profile, and desktop control.

## The Footprint

After a turn, the Footprint lists what actually happened on disk or left this PC — for example files written, deletes sent to the Recycle Bin, and cloud calls. Prefer the Footprint over trusting the model’s wording alone.

## Drag-and-drop

Drop a file onto the chat to attach it for that turn. MiniAI can then read or summarise what you attached without you typing the full path.

## Approvals

When MiniAI wants to do something sensitive it stops and asks you:

| Prompt | What to do |
|---|---|
| `Allow? [yes/no]` | Type `yes` or `no`. Anything else means no. |
| `Type <action> to approve` | Type the exact action name (for example `write_file`). Plain `yes` is not enough. Used when the session has read untrusted web content, or for some install actions. |
| Desktop trust / task grant | Let MiniAI read or briefly control a specific app window for this turn. |

Chat replies like “sure, go ahead” are **not** approvals — only the prompt answers count.

Deletes go to the **Recycle Bin**. Overwrites keep a backup under `%LOCALAPPDATA%\MiniAI\backups\`.

## Running slowly

Typical healthy speed with a few GB free is about **12–13 tokens/s**. If free RAM is very low (other big apps open), MiniAI can drop toward **8 tok/s** or worse. Close heavy browser tabs / editors when you care about speed. The status chip’s System popover shows free RAM and model health.

## Low-memory hint

If free RAM is under about **2.5 GB**, or the last call was slower than 90% of this model’s reference speed, MiniAI may show one gentle line under the status chip:

> Your PC is low on memory — closing big apps (browser tabs, editors) makes MiniAI faster.

It appears at most once per hour. MiniAI never closes your apps for you.

## What MiniAI can’t do yet

- Vision / images as a first-class input (no screenshot understanding by default).
- Very long multi-file coding projects that need many fix–test loops (the model often stops after one failing pytest run).
- Opening arbitrary `localhost` pages in normal use (loopback is blocked on purpose; only a special eval harness can allow one fixture).

## If something breaks

1. **Restart MiniAI** (quit the window, start again with `pythonw -m app`).
2. Use **Reload model** from the status chip / System popover so Lemonade reloads Qwen cleanly.
3. **Restart the PC** if Lemonade or the GPU path is wedged and Reload does not help.

Optional check from a terminal (with the venv):

```text
.venv\Scripts\python.exe -c "from scripts.check_model_state import check_model_state; print(check_model_state()['verdict'])"
```

You want `OK`. If you see `DEGRADED`, try Reload model / restore, then re-check.
