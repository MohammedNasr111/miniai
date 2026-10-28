# Round 8e report — window-targeted captures; remove wrong-window screenshots

**Date:** 2026-10-29  
**Full diffs:** `logs/review_20261029-0708_round8e.log` (attach).  
**Hard rules kept:** no secrets; no history rewrite / no force-push; gate/tiers/BLOCKED/protected/firewall unchanged.

## Part 1 — Wrong-window audit (Round 7+ `actual_*`)

Checked every `app/design/actual_*.png` committed since Round 7 (v9–v13 + r8*). MiniAI’s UI is dark (`--slate` ≈ rgb 18,24,33). Heuristic: mean RGB of a downscaled thumb + brand-mark blue hits in the top-left rail.

| File | Verdict |
|------|---------|
| `actual_r8c_cloud_quota_footprint.png` (pre-8e) | **NOT MiniAI** — mean ≈ (251,251,251) light UI (Claude desktop). **Removed** (normal delete; history not rewritten). |
| `actual_r8_cloud_settings.png` | MiniAI (dark) |
| `actual_r8b_cloud_fallback.png` | MiniAI (dark) |
| `actual_v9_*` (8 files) | MiniAI (dark) |
| `actual_v10_*` (7 files) | MiniAI (dark) |
| `actual_v11_*` (3 files) | MiniAI (dark) |
| `actual_v12_*` (3 files) | MiniAI (dark) |
| `actual_v13_*` (2 files) | MiniAI (dark) |
| `actual_v5_taskbar_icon_tight.png` | Taskbar crop (light shell chrome + MiniAI icon pixels) — not another app’s chat window; kept |

**Removed (only wrong-window full UI capture):** `app/design/actual_r8c_cloud_quota_footprint.png` (then retaken in Part 4).

## Part 2 — Capture only the MiniAI HWND

New shared helper: `scripts/miniai_capture.py`

- Finds window title **exactly** `MiniAI`.
- Forces foreground (`AttachThreadInput` / topmost pulse); aborts with `CAPTURE_ERR=…` and **writes no file** if title ≠ MiniAI or `GetForegroundWindow() != hwnd`.
- Primary grab: `PrintWindow` / `BitBlt` of that HWND’s own bits (not “whatever is on screen”).
- Screen-crop fallback only after a fresh foreground verify.
- Offline test: `scripts/test_miniai_capture.py` → **FAILURES=0**.

All `scripts/capture_*.py` now call `capture_miniai_window` (ImageGrab-of-rect / full-desktop paths removed).

## Part 3 — Report honesty

Reports may describe:

1. What is verifiable in the PNG (dark MiniAI chrome, visible panels), and  
2. DOM text, **labelled as DOM text** (companion `.txt` / `FP_CHECK`).

They must not narrate PNG content from DOM alone.

## Part 4 — Retake + quick

Retake via fixed capture: `app/design/actual_r8c_cloud_quota_footprint.png`  
- Capture log: `SAVED=… size=(1100, 720) … hwnd=…` (`logs/_qa_round8e_capture2.txt`)  
- Mean RGB ≈ (34, 38, 46) — dark MiniAI (not the prior ~251 white Claude frame)  
- SCENE_R8C **PASS** with `png=True`

**Image (verifiable in PNG):** MiniAI window chrome; dark UI; run heading area; Footprint side panel open with “Left this PC” ledger rows visible.

**DOM text (not the PNG):** `FP_CHECK` reports `fpVisible=True`, `gemLines=3`, ask=`Write a tiny hello webpage in the workspace.`, and body text includes `Gemini stopped partway (quota (429 RESOURCE_EXHAUSTED)); this PC finished the answer.` — see `actual_r8c_cloud_quota_footprint.txt` section `FP_CHECK (DOM text, not the PNG)`.

| Check | Result |
|-------|--------|
| `test_miniai_capture.py` | **FAILURES=0** |
| Quick suite | **16/16**, Safety **9/9 PASS** (`logs/_qa_round8e_quick.txt`, `logs/eval_20261029-070733.json`) |

## Commits (pushed)

| Hash | Message |
|------|---------|
| `bdcb8d0` | Round 8e: window-targeted captures; remove wrong-window screenshots |
