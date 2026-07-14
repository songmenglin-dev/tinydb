# POLISH-CLI — Fix two CLI defects after B9 demo verification

## Defects observed
```
tinydb> select * from user;
col0 col1
1    tom
```
Two issues:
1. **Column-name fallback** — `SELECT * FROM user` shows headers as `col0`/`col1` instead of `id`/`name`.
2. **DDL silent** — `CREATE TABLE user(...)` returns no visible confirmation in the REPL.

## Goal
Fix both with minimal changes to `cli/format.py` + `cli/repl.py` + `cli/argparse_ext.py`. NO changes to executors / planner / storage layers.

## Fix 1: Column-name resolution for `SELECT *`

The executor already knows the base table for `Project` (since `Plan.table` is a `@property` returning the leaf's table). The cleanest fix: plumb the **column names** from the base table's schema into the executor result so `format_rows` can use real column names instead of `col0`/`col1`.

The simplest implementation:
- Executor returns `list[tuple]` AND accepts an optional `result_columns: list[str] | None` argument that gets attached.
- `SELECT *`: the planner already calls `Project.items=Select.columns` (T-5.1). Today the items are the AST nodes. When `Select.columns` is `[Star]`, the planner can substitute the catalog's column names into `Project.columns`. (Already done? Let me check.)

Actually re-checking: B5 carries over that **`Project.items`** is the parallel-array with `columns`. The columns list is `table.declared_columns`. So the BUG might already be elsewhere — let me investigate before deciding.

## Fix 2: DDL confirmation

In `cli/repl.py` (and the one-shot `run_one` path), after `db.execute(...)`:
- If result is `[]` AND the statement was DDL, print `"OK"`.
- Else format as before.

To detect DDL we can sniff the type: parse the SQL first, dispatch based on `isinstance(stmt, CreateTable | DropTable)`.

OR simpler: check `rows == [] and not errored`. Hmm but `SELECT * FROM empty` also returns []. So this approach conflates empty SELECT vs DDL.

Cleanest: in the REPL, branch on the statement type to decide whether to print "OK".

## Files to Modify

### `src/tinydb/cli/repl.py`
- After successful `db.execute(stmt)`: if stmt is `CreateTable`/`DropTable`/etc., print "OK".

### `src/tinydb/cli/format.py`
- The column-name fallback already works — the executor's `Project(columns=[...])` should already have the right list. **Verify**: run demo in REPL and see if the issue persists after we just check executor.

### `src/tinydb/cli/argparse_ext.py`
- The one-shot path (`-c "..."`) should also print "OK" for DDL.

## Tests Required

`tests/cli/test_polish.py`:
1. REPL `SELECT * FROM user` → output contains `id` and `name`, NOT `col0`/`col1`.
2. REPL `CREATE TABLE x (id INT)` → output contains `OK`.
3. Subprocess `python -m tinydb --db x.db -c "CREATE TABLE ..."` → exit 0 + "OK" in output.
4. Subprocess `python -m tinydb --db x.db -c "INSERT ..."` → exit 0 + (1,) in output.

## Verification

- `python -m pytest tests/ -q` (817 → still passing).
- `python examples/demo.py` exits 0.
- Manual REPL test: header columns show real names, DDL prints OK.

## Commit
`fix(cli): real column headers for SELECT * + OK confirmation for DDL`

## Report
`/mnt/c/sml/project/py_project/tinydb/changes/tinydb/sdd/btree/POLISH-CLI-report.md`
