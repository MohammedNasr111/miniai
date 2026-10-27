# Round 8 report — Gemini hybrid brain with code-enforced privacy routing

**Date:** 2026-10-27  
**Full diffs / artifacts:** `logs/review_20261027-*_round8.log` (attach; reviewer cannot see tool output).  
**Part 0:** Round 7f completed first — commit `aa01756`, report `ROUND_7F_REPORT.md`.

## Provider choice + endpoint verified

- **Choice:** Google's official OpenAI-compatible Gemini API  
  `https://generativelanguage.googleapis.com/v1beta/openai/`  
  (documented at https://ai.google.dev/gemini-api/docs/openai). No third-party gateway.
- **Implementation:** `llm/gemini/provider.py` — same `chat` / `chat_stream` shape as LemonadeProvider; Flash model picked at runtime from `GET /models` (fallback `gemini-2.0-flash` if list fails).
- **Host lock:** `assert_allowed_base_url` refuses any host other than `generativelanguage.googleapis.com`. Offline test PASS (`logs/_qa_round8_gemini_provider.txt`).
- **Live call with a real key:** SKIPPED (`MINIAI_TEST_GEMINI_KEY` unset). Endpoint shape verified via docs + mocked POST to the allowed host only.
- **429:** raises `GeminiQuotaError` → UI/local fallback message; no retry loop. **5xx/timeout:** one retry, then fall back.

## Part 1 — Key storage proof

- Path: `%LOCALAPPDATA%\MiniAI\secrets\gemini.bin` (DPAPI CryptProtectData, current user).
- UI: Cloud brain settings (palette + rail) — password input, Save, Remove, status line. Key never returned to WebView after save.
- **Protected paths:** `%LOCALAPPDATA%\MiniAI` is already a protected root via `security/protected_paths._miniai_data_root()`, so `secrets\` is covered **without changing gate / protected-path lists**. Confirmed by `is_protected_path(secrets_dir()/gemini.bin)` in tests.
- Offline `scripts/test_gemini_key.py` **FAILURES=0**: save → reload → decrypt; plaintext absent from bin; Remove deletes file; key absent from chats/temp logs greps (`logs/_qa_round8_gemini_key.txt`).
- Commit: `1f1dce7` Round 8 Part 1.

## Part 2 — Provider

- Commit: `3bcaddb` Round 8 Part 2.
- Offline host-lock + Flash pick + mocked chat: **FAILURES=0**.

## Part 3 — Privacy routing (code-enforced)

- Composer: **Send to cloud** (Ctrl+Enter); plain Send stays local.
- Cloud allow-list: `web_research`, `fetch_url`, `calculate`, `ws_*`, `run_*`, `install_package`. Executor denies anything else with:  
  `This needs your files, so I can't send it to the cloud. Send it normally to answer on this PC.`
- Cloud system prompt: no user folder paths, no memories, no local-turn history (optional prior cloud turns only).
- Gate still applies (tickets unchanged).
- Offline `scripts/test_cloud_routing.py` **FAILURES=0**: tool list has no forbidden tools; mocked request body has no memory/folder paths; forbidden message fires (`logs/_qa_round8_cloud_routing.txt`).
- Commit: `c90c237` Round 8 Part 3–4.

## Part 4 — Honesty UI

- Run header: `Answered by Gemini (cloud)` or local model name (`.meta-brain`).
- Footprint “Left this PC”: `Sent to Google Gemini: your question (N characters) + N web pages` from captured request meta (not an estimate).
- Rail: `Cloud: not connected` / `Cloud: connected` / `Cloud: <model>`.

## Part 5 — Measure (pre-registered BEFORE run)

Pre-registered rule file: `logs/round8_part5_preregistered.md`.

| Rule | |
|------|--|
| Default-enable Send to cloud only if | (a) cloud safety 100% AND (b) ≥2 pass wins vs Round 6b hard baseline, OR equal passes and ≥40% faster |
| Else | Experimental checkbox only |

| Env | Result |
|-----|--------|
| `MINIAI_TEST_GEMINI_KEY` | **not set** |
| Live cloud safety + hard tasks | **SKIPPED** |
| Default Send-to-cloud | **OFF** (`cloudEnabledDefault = false`); available via Settings → Experimental: cloud brain |

## Part 6 — Quick suite + screenshots

| | |
|--|--|
| Safety | **PASS** (9/9) |
| Tasks | **16/16** |
| Eval | `logs/eval_20261027-234947.json` |
| Log | `logs/_qa_round8_quick.txt` |

**Screenshots**
- Settings (key field EMPTY, type=password, status Not connected): `app/design/actual_r8_cloud_settings.png` (+ `.txt`). SCENE_SETTINGS **PASS**.
- Cloud run header + footprint: **SKIPPED** (no test key for a live cloud turn).

## Commits (pushed)

| Hash | Message |
|------|---------|
| `aa01756` | Round 7f (Part 0) |
| `1f1dce7` | Round 8 Part 1: DPAPI key + settings |
| `3bcaddb` | Round 8 Part 2: Gemini provider |
| `c90c237` | Round 8 Part 3–4: privacy routing + honesty UI |
| *(this)* | Round 8 report |

After this, the user pastes a real key; the architect hand-tests cloud turns.
