# T-9.1 — README + examples/demo.py

## Files

- `README.md` (root) — 10 sections, ~135 lines.
- `examples/demo.py` (new) — runnable 10-step demo, ~145 lines.

## Sections in README

1. Title + tagline.
2. Features (the 7 capabilities).
3. Install (git clone + `pip install -e .`).
4. Quick Start (5-line snippet).
5. CLI (`-c`, REPL, meta-commands).
6. Limitations / Out of Scope (explicit list).
7. Architecture overview (5-layer table).
8. Running tests (`pytest` + coverage gate).
9. License (MIT).
10. Status (v0.1.0).

## demo.py steps

1. Open a temp DB.
2. CREATE TABLE users + orders.
3. INSERT 5 users, 3 orders.
4. SELECT * (ordered).
5. PRIMARY KEY auto-index inspect.
6. SELECT WHERE id = 3 (IndexScan).
7. UPDATE age on a row.
8. Aggregations: COUNT(*), AVG(age).
9. Transaction: BEGIN / INSERT / COMMIT.
10. Cleanup: DROP TABLE, close DB.

## Verification

```bash
$ python examples/demo.py
tinydb v0.1 demo — db at /tmp/tinydb-demo-.../demo.db
...
tables remaining: []
$ echo $?
0
```

Exit code 0.

## Deviations from brief

- Brief step 5 said "CREATE INDEX on `users(name)`".  v0.1 SQL parser
  does NOT support `CREATE INDEX` (DDL is CREATE/DROP TABLE only).
  Replaced with step 5 = inspect the auto-created PK index via
  `db.catalog.list_indexes()` (which surfaces `pk_users_id`) and step
  6 = SELECT WHERE on the indexed `id` column to demonstrate
  IndexScan.  No production code was changed; the deviation is purely
  in `examples/demo.py`.
- Brief step 7 said `UPDATE age WHERE name = 'alice'`.  Since step 6
  changed from `name` to `id`, step 7 was updated for consistency.
- Brief step 10 mentioned DROP TABLE; demo does that plus closes the
  DB.  No deviation beyond matching the brief.

## Commit

- `b726643` — docs: T-9.1 README + examples/demo.py