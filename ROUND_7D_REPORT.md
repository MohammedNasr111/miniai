# Round 7d Report — polish from architect hands-on (20:08–20:12)

**Full new-file contents and diffs:** `logs/review_20261026-2101_round7d.log` (attach that file; do not rely on tool output above).

## Part 1 — Folders are not files

**Cause:** “Make a folder…” used `create_file` on an extensionless Desktop path → empty *file*.

**Fix:** `create_folder(path)` (CONFIRM, protected-path check, refuse if exists, parents only under an existing known user folder). Ticket: “Create folder” / “Don't create”, consequence “A new folder will be created on this PC.” Mapped in action classes (amber change), footprint (“Created folder …”), action-claim (“created a folder”). `create_file` refuses extensionless paths when the user text mentions “folder”, telling the model to call `create_folder`. Turn user text via `tools/filesystem/turn_context.py`.

**Test:** `scripts/test_create_folder.py` FAILURES=0 (offline + live ×2). Commit `05dbf51`.

## Part 2 — Show the code checks

**Cause:** After create/delete, Footprint “Verified by code 0” and no green verify node even when guards ran.

**Fix:** `agent/post_action_verify.py` does independent `os.path.exists` / `isdir` checks (not the tool return string). Passing checks add green verify nodes (“File exists on disk” / “Folder exists on disk” / “File is in the Recycle Bin”) and Footprint `record_verify` entries. Action-claim / listing / decline guards that run also get verify nodes when they fire.

**Test:** `scripts/test_post_action_verify.py` FAILURES=0. Commit `949c262`.

## Part 3 — Honest wording after a decline

**Cause:** After decline, the model said “It seems I couldn't create…” (reads like a failure).

**Fix:** When the turn’s only mutating tool call(s) were denied, `agent/decline_honesty.py` replaces the first sentence with “You declined, so nothing was changed.” (keeps useful remainder).

**Test:** `scripts/test_decline_honesty.py` FAILURES=0. Commit `1902a91`.

## Part 4 — Generalise listing honesty

**Cause:** Round 7c honesty only rewrote biggest-file answers.

**Fix:** For any turn that used `list_directory`, names presented as in that folder must appear in the listing; unknowns are stripped with “⚠ Removed N name(s) that weren't in the folder listing.” Biggest-files rewrite remains a special case of the same rule.

**Test:** `scripts/test_listing_honesty.py` FAILURES=0. Commit `351814d`.

## Part 5 — Prove and report

**Quick suite:** Safety **PASS**, tasks **16/16** (`logs/eval_20261026-205634.json`, `logs/_qa_round7d_quick2.txt`). Self-check `logs/selfcheck_latest.json` → `16 of 16, 2026-10-26`. (First quick attempt was 15/16 on a flaky coding SyntaxError; second full quick was clean 16/16.)

**Screenshots (v12, real interaction + DOM asserts):** `scripts/capture_v12_ui.py` → `app/design/actual_v12_summary.json`. **3/3 ok, unique md5.**

| Scene | Asserted state | png | txt | md5 |
|-------|----------------|-----|-----|-----|
| folder_ticket | Open ticket with Create folder / Don't create | `actual_v12_folder_ticket.png` | `actual_v12_folder_ticket.txt` | `24084cdb1aebc15daec7017ce2aec725` |
| verify_delete | `.step[data-k=verify]` + Footprint Verified ≥1 after delete | `actual_v12_verify_delete.png` | `actual_v12_verify_delete.txt` | `b2ee71f459a5c259a457ff180fe08214` |
| declined_wording | Denied step + “You declined, so nothing was changed.” | `actual_v12_declined_wording.png` | `actual_v12_declined_wording.txt` | `4345880c29c4b1703821f149dafb6ba8` |

## Commits (this round)

| Hash | Message |
|------|---------|
| `05dbf51` | App: create_folder tool; refuse extensionless create_file for folder requests |
| `949c262` | App: post-action disk verify nodes and Footprint verified-by-code entries |
| `1902a91` | App: replace decline answers with You declined, so nothing was changed |
| `351814d` | App: general listing honesty for any list_directory turn |
| *(final)* | Round 7d: create_folder, visible code checks, decline wording, general listing honesty |
