# Round 13 Part 6 — qa_h_code_cli diagnosis

Evidence: `logs/_qa_round13_code_cli_x2.txt`, `logs/eval_20261101-100714.json`

## Repeat 1/2 — FAIL (pytest_ok=False; 7 passed, 1 failed)

Edits (in order):
1. `create_folder` under MiniAI project path → blocked (correct product guard).
2. `ws_write` empty `command_line_expense_tracker/main.py` and empty test file.
3. `run_tests` → "no tests ran".
4. `ws_write` full `tests/test_expense_tracker.py` importing `ExpenseTracker` from main.
5. `run_tests` → ImportError (main still empty).
6. `ws_write` full `main.py` with SQLite `ExpenseTracker`.
7. `run_tests` → **7 passed, 1 failing**.

Failing test quote from grader detail:
```
FAILED command_line_expense_tracker/tests/test_expense_tracker.py::test_load_from_database
AssertionError: assert 7 == 1
```

Auto-test line:
```
[AUTO-TEST] … Tests: 7 passed, 1 failing: fail test_load_from_database — test_expense_tracker.py:45 — assert len(loaded_tracker.expenses) == 1
```

Re-ran tests after each substantive edit: **yes** (3 `run_tests` approvals). After the final failure, **no further edit**.

## Repeat 2/2 — FAIL (pytest_ok=False; 2 passed, 2 failed)

Edits:
1. Again tried project-dir `create_folder` / `create_file` → blocked.
2. `ws_write` `main.py` (functional SQLite helpers + demo `main()` that inserts sample rows).
3. `ws_write` tests that share the default `expenses.db` without cleanup.
4. One `run_tests` → 2 fail.

Failing tests quote:
```
FAILED …::test_get_expenses
FAILED …::test_get_expenses_by_category
assert expenses_by_category['Food'] == 61.49
```

Auto-test:
```
[AUTO-TEST] … 2 passed, 2 failing: fail test_get_expenses — assert len(expenses) == 2; fail test_get_expenses_by_category — assert …['Food'] == 61.49
```

Re-ran after edits: **once only**; did not iterate on the failures.

## Classification

- **Not** pytest rootdir / PYTHONPATH infrastructure (imports worked once `main.py` existed; runner executed tests).
- **Not** step-budget exhaustion (wall ~190–235s; finished with a final answer after the last test run).
- Cause: **model ability** — buggy shared SQLite state across tests / incorrect load semantics; stopped after seeing failures instead of isolating the DB or fixing asserts.
- Action: **change nothing**.
