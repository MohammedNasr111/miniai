# MiniAI user guide

Plain-language guide for day-to-day use. For design detail see
[ARCHITECTURE.md](ARCHITECTURE.md).

## Start a chat

1. Make sure Lemonade Server is running with your chat model loaded.
2. From the MiniAI folder, with the project virtualenv active:

```text
python -m scripts.chat
```

3. Type a request and press Enter. MiniAI may ask you to approve actions
   before it does them (see below).
4. Useful commands inside the chat:
   - `/status` — taint sources, turn count, last prompt size
   - `/new` — start a fresh session (clears history, browser, taint)
   - `/exit` — quit

## Example requests (by ability)

- **Knowledge (your indexed docs):**  
  “Search the knowledge base for PAGE ONE MARKER and say which page it is on.”
- **Memory:**  
  “Remember that my project codeword is BLUE-ORKNEY.” then later  
  “What project codeword did I ask you to remember?”
- **Web:**  
  “What is the latest stable Python version on python.org?”  
  “What do mitochondria produce?”
- **Files:**  
  “Create `C:\Temp\note.txt` with the text hello.”  
  “Delete `C:\Temp\note.txt`.” (goes to the Recycle Bin after you approve)
- **Counting / folders:**  
  “How many files are in `C:\Temp\myfolder`? Use list_directory.”
- **Browser:**  
  “Open Wikipedia, find Adenosine triphosphate, and quote the first sentence.”
- **Desktop:**  
  “List my open windows, read the Notepad window, and insert a sentence at the end.”  
  (You will be asked to trust the app and to begin a task.)
- **Coding (sandboxed workspace):**  
  “In the workspace, write a word-count function with pytest tests and run them until they pass.”

## What the permission prompts mean

MiniAI prints a short description, then waits for you.

| Prompt style | What to type | Meaning |
|---|---|---|
| `Allow? [yes/no]:` | `yes` or `no` | Approve or deny this one action. Anything other than `yes` denies. |
| `Type <action> to approve, …` | Exact action name (e.g. `write_file`, `browser_open`, `install_package`) | **Typed confirmation.** Used when the session has read untrusted web/page content (tainted), or always for package installs. Typing `yes` is **not** enough. |
| Desktop read: `session` / `always` | `session`, `always`, or refuse | Allow reading that app for this session, remember forever (trusted apps file), or deny. |
| Desktop task grant | Usually `yes` (or typed name if tainted) | Allows presses/typing in that app for the rest of this user turn. |

Chat replies are never approvals — only answers typed at these prompts count.

## How to undo things

- **Deleted files:** MiniAI moves them to the **Recycle Bin**. Restore them from the Recycle Bin in Explorer (not permanently deleted by MiniAI).
- **Overwritten files:** Before overwrite, MiniAI copies the old file to  
  `%LOCALAPPDATA%\MiniAI\backups\` (timestamped name). Copy it back if you need the previous version.
- **Code workspace:** Changes under the isolated workspace are versioned. Ask MiniAI to show history (`workspace_history`) and restore a commit (`workspace_restore`) — you will be asked to confirm restore. History is kept; restore makes a new commit.

MiniAI will not modify its own project folder, browser profile, or `%LOCALAPPDATA%\MiniAI` settings via file tools.

## How to stop it

- **Ctrl+C** during a chat turn cancels that turn and rolls the conversation back to before the message. Actions you already approved are **not** undone.
- **Desktop tasks:** If you move the mouse or type on the keyboard while a desktop task grant is active, MiniAI asks whether to continue. Answering no ends the grant.
- Close the chat with `/exit`, or close the MiniAI browser window if a browser tool left it open.

## Firewall rule (code runner)

Sandboxed code runs with a dedicated Python binary. To block that binary from using the internet, run **once as Administrator**:

```text
powershell -ExecutionPolicy Bypass -File scripts\setup_runner_firewall.ps1
```

To remove the rule (also as Administrator):

```text
powershell -ExecutionPolicy Bypass -File scripts\setup_runner_firewall.ps1 -Remove
```

The rule name is `MiniAI code runner - block internet`. Without it, sandboxed code can still reach the network (the runner will report the rule as not installed).

## Run the quick evaluation

With Lemonade up and the venv active:

```text
python -m eval.run --suite quick
```

Optional: `--model Qwen3-14B-GGUF` if the default large model is slow to load.  
Safety tasks must all pass (report headline **Safety: PASS**).  
`--save-baseline` updates `eval/baseline.json` only when safety passes.  
See `eval/last_report.md` after a run. Infrastructure retries after server errors are listed under **Stability**.

## Known limitations (plain words)

These are design trade-offs, not bugs to “fix” by trusting the model more:

- The local model is weak at exact counting; prefer having it call tools that compute the number.
- It may invent reasons when it does not know something — check the tool output and prompts.
- Duplicate identical tool calls in one session are blocked on purpose.
- Web answers depend on what search finds that day; there is no guarantee of a perfect source.
- Quoted text is checked against retrieved pages; paraphrase-as-quote is flagged, not rewritten.
- Multi-step browser flows with the smaller model are shaky; wrong element guesses are skipped and it can try again.
- Knowledge search reports freshness from when files were indexed; it does not re-index by itself. A change that keeps the same file modification time can look “current” when it is not.
- A hostile website can change what its own buttons do after MiniAI has looked at them; MiniAI uses its own browser profile, not your logged-in browser.
- Content inside iframes is invisible to the browser tools.
- Typed text or form submits can be redirected by page scripts; the prompt shows the declared destination, not every script trick.
- Reading memory does not ask you first; sending memory out via browser/URL tools still needs your confirmation (and typed confirmation when tainted).
- Desktop actions apply to the active tab/document; if the window title changes, MiniAI refuses until you read again.
- Sandboxed code runs at low integrity: it should not write up into your normal files, but it can still **read** many of your files. Network block needs the firewall rule above.
- Workspace shortcuts/junctions that point outside the workspace are refused for MiniAI’s file tools; sandboxed code may still try to create them.
- Chat timeouts roll back that turn’s messages; approved side effects are not auto-undone.
