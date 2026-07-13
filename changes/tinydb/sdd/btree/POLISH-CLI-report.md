# POLISH-CLI — Report

## Summary

Two CLI defects fixed: (1) `SELECT *` now shows real column names instead of
the `col0`/`col1` fallback; (2) DDL (`CREATE`/`DROP TABLE`) now prints `OK`.

## What changed

### New helper: `executor.ops.result_columns`
`/src/tinydb/executor/ops.py:result_columns(plan)` walks a plan tree and
returns the result-row column labels it can carry:
- `Sort` / `Limit` wrappers are unwrapped (no schema of their own).
- `Project.columns` → returned verbatim.
- `Aggregate`: `keys + "<func>(<col>)"` labels per its row layout.
- Otherwise `None` (DML leaf plans, bare SeqScan without a Project).

The helper is the single source of truth that both the REPL and the
one-shot CLI dispatcher consult.

### `cli/argparse_ext.py` (`_run_one`)
- Parses the SQL first via `tinydb.sql.parser.parse(sql)` to detect DDL.
- For `CreateTable`/`DropTable`: prints `OK` on success, error on
  TinydbError.
- Otherwise: plans the statement, grabs `result_columns(...)`, runs it,
  and feeds the columns to `format_rows`.
- DML affected-count rows (`[(n,)]`) render as plain `<n> row(s)`
  instead of a misleading `col0` table.

### `cli/repl.py` (`run_repl`)
- Mirrors the one-shot dispatch path: parse → DDL `OK` → plan →
  `result_columns` → execute → format.
- INSERT/UPDATE/DELETE affected-count prints as plain text.

### `tests/cli/test_polish.py` (new)
9 cases covering both REPL and subprocess one-shot paths:
- REPL `SELECT * FROM user` shows `id`/`name`, no `col0`/`col1`.
- REPL `SELECT id, name FROM user` shows column names.
- REPL `SELECT id+1 FROM t` doesn't crash on synthetic columns.
- REPL `CREATE TABLE` / `DROP TABLE` → `OK` in output.
- subprocess `python -m tinydb --db x.db -c 'CREATE ...'` → exit 0 + `OK`.
- subprocess `SELECT *` after CREATE+INSERT → real names in stdout.

### `tests/cli/test_repl.py` (updated)
`test_select_outputs_table` was asserting `col0 in joined` — that
assertion was implicitly documenting the bug. Updated to assert the
correct contract (`id` and `name` are present; data row appears).
`test_insert_shows_affected_count` continues to pass because the
affected-count string still contains `1`.

## TDD timeline

| Phase | Result |
|-------|--------|
| Baseline | 817 passing |
| RED (`tests/cli/test_polish.py`) | 7 failed, 2 passed |
| GREEN (helper + REPL + dispatcher) | 9 passed |
| Update legacy `col0` assertion | 826 passing (817 + 9 new) |

## Files

- New: `tests/cli/test_polish.py`
- Modified:
  - `src/tinydb/executor/ops.py` (added `result_columns`)
  - `src/tinydb/executor/__init__.py` (re-export)
  - `src/tinydb/cli/argparse_ext.py` (DDL `OK` + column plumbing)
  - `src/tinydb/cli/repl.py` (DDL `OK` + column plumbing)
  - `tests/cli/test_repl.py` (legacy `col0` assertion corrected)

## File-cap compliance

| File | Lines | Cap |
|------|-------|-----|
| `cli/format.py` | 88 | ≤ 130 |
| `cli/repl.py` | 219 | ≤ 220 |
| `cli/argparse_ext.py` | 119 | ≤ 130 |

## Verification

- `pytest tests/ -q` → 826 passed (was 817; 9 new).
- `python examples/demo.py` → exit 0.
- Manual REPL: `SELECT *` now shows the schema column names; `CREATE TABLE`
  prints `OK`; `INSERT INTO ...` prints `1 row(s)`.
