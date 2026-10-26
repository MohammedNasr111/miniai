# Round 7e Report — scope code-check nodes to their own turn

**Full new-file contents and diffs:** `logs/review_20261026-2150_round7e.log` (attach that file).

## Part 1 — Verify events leak across turns

**Cause:** `post_action_verify` scanned the whole session transcript (prior deletes reappeared). Guard nodes also fired on empty claim/quote checks, and decline set `fixed` which added an amber note + extra “Noted that you declined” verify.

**Fix:** Track create/delete targets in per-turn memory (`note_fs_verify_target` / `get_fs_verify_targets`). Verify nodes only when a guard checked something relevant (`claims_present` / quote claims / this-turn disk checks). Decline: muted denied node + wording only — no extra verify, no amber note. Footprint `record_verify` dedupes by `(turn_id, label)`.

**Test:** `scripts/test_verify_scope.py` FAILURES=0. Commit `35a77e7`.

## Part 2 — Truthful verify wording

**Cause:** Node said “File is in the Recycle Bin” after only checking `not os.path.exists`.

**Fix:** Default wording is `Gone from <parent> (sent to the Recycle Bin)`. “is in the Recycle Bin” only when Shell.Application Namespace(10) lists the basename. Create checks still say “File/Folder exists on disk”.

**Test:** `scripts/test_verify_wording.py` FAILURES=0. Commit `018ff9c`.

## Part 3 — Folder wording and stale ticket

**Cause:** Folder deletes used “Delete 1 file” / “Deleted a file”. After approve, poll could re-show a live ticket beside the collapsed “You approved” line.

**Fix:** `delete_file` descriptions use “Move folder to Recycle Bin”; ticket/trace/footprint use “folder” when `was_dir`. JS: ignore re-delivery of an answered nonce; settle (collapse) before `approval_reply`.

**Test:** `scripts/test_folder_delete_wording.py` FAILURES=0. Commit `cc5f906`.

## Part 4 — Prove and report

**Quick suite:** Safety **PASS**, tasks **16/16** (`logs/eval_20261026-214918.json`). Self-check `16 of 16, 2026-10-26`.

**Screenshots (v13, DOM asserts):** `scripts/capture_v13_ui.py` → `app/design/actual_v13_summary.json`. **2/2 ok, unique md5.**

| Scene | Asserted state | png | md5 |
|-------|----------------|-----|-----|
| declined_no_leak | Last run: denied node, **0** verify nodes, decline wording | `actual_v13_declined_no_leak.png` | `4c2486ca3f60b0c6cb6a8d34061b921e` |
| folder_delete_ticket | Open ticket “Delete 1 folder” / “Delete folder” | `actual_v13_folder_delete_ticket.png` | `94e1917e7069fadfa9adcfd840945fb6` |

## Commits (this round)

| Hash | Message |
|------|---------|
| `35a77e7` | App: scope verify nodes and Footprint checks to the current turn |
| `018ff9c` | App: truthful verify wording (Gone from … unless Recycle Bin checked) |
| `cc5f906` | App: folder delete wording and no stale live tickets after approve |
| *(final)* | Round 7e: turn-scoped code checks, truthful verify wording, folder wording, no stale tickets |
