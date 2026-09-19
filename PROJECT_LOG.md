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
