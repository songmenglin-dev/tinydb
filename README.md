# tinydb

> A zero-dependency, single-file embedded relational database in pure Python.

`tinydb` is a tiny SQL engine that fits in one process.  It gives you
`CREATE TABLE` / `INSERT` / `SELECT` / `UPDATE` / `DELETE`, transactions
with crash recovery, a B-tree secondary index, and an interactive CLI —
with **no third-party runtime dependencies**.

It is built as a teaching/embedded database: the parser, planner,
executor, B-tree, heap, WAL, and recovery live in one package, and
every layer is testable in isolation.

---

## Features

1. **SQL DDL + DML** — `CREATE TABLE`, `DROP TABLE`, `INSERT`, `SELECT`,
   `UPDATE`, `DELETE`, with `WHERE`, `ORDER BY`, `LIMIT`, `OFFSET`,
   `GROUP BY`, and the standard aggregations (`COUNT`, `SUM`, `AVG`,
   `MIN`, `MAX`).
2. **Static type system** — `INT`, `FLOAT`, `TEXT`, `BOOL`, `DATE`,
   `TIME`, `DATETIME`, `DECIMAL`, `BLOB`, `JSON` with strict coercion.
3. **B-tree secondary indexes** — including composite-key indexes and
   auto-created unique indexes for `PRIMARY KEY`.
4. **Transactions (ACID)** — single-writer `WriteLock` + append-only
   `WAL` + `Recovery` (REDO/UNDO) + periodic `Checkpoint`.
5. **Interactive CLI / REPL** — run a single statement with `-c`, or
   drop into the REPL with meta-commands (`.tables`, `.schema`,
   `.exit`, …).
6. **Crash safety** — committed transactions survive process exit and
   machine crash; uncommitted writes are rolled back on reopen.
7. **Zero runtime dependencies** — pure Python stdlib; `pytest` only
   for the test suite.

---

## Install

`tinydb` runs straight from a source-tree checkout — there are no
compiled extensions and no third-party packages at runtime.  Clone the
repo and you can `import tinydb` directly:

```bash
git clone <repo-url> tinydb
cd tinydb
pip install -e .   # editable install; no runtime deps
python -c "import tinydb; print(tinydb.__version__)"
```

A release on PyPI is on the roadmap (DP-7); until then `pip install -e .`
is the canonical way to expose `tinydb` on your `PYTHONPATH`.

---

## Quick Start

```python
import tinydb

with tinydb.open("/tmp/demo.db") as db:
    db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES (1, 'alice')")
    for row in db.execute("SELECT * FROM users"):
        print(row)
```

`db.execute(sql)` returns a list of tuples for `SELECT`, a single
`[(affected_count,)]` row for DML, and `[]` for DDL.  Any failure
raises `tinydb.errors.TinydbError` (or a subclass).

---

## CLI

Run a single SQL statement and print the result rows:

```bash
python -m tinydb --db /tmp/demo.db -c "SELECT * FROM users"
```

Drop into the REPL (no `-c`):

```bash
python -m tinydb --db /tmp/demo.db
```

Inside the REPL:

```text
tinydb> .tables
users
tinydb> SELECT * FROM users;
+----+-------+
| id | name  |
+====+=======+
| 1  | alice |
+----+-------+
tinydb> .exit
```

Supported meta-commands: `.tables`, `.schema`, `.help`, `.exit` /
`.quit`.  See `examples/demo.py` for a runnable end-to-end walkthrough.

---

## Limitations / Out of Scope

v0.1 deliberately omits these; they are not bugs:

- **JOIN queries** — only single-table `SELECT`.
- **Multi-process / multi-thread concurrency** — a single writer at a
  time via `WriteLock`; concurrent readers see committed data only.
- **`ALTER TABLE`** — schemas are immutable after `CREATE TABLE`.
- **Views, triggers, stored procedures.**
- **Foreign keys / referential integrity.**
- **Network / client-server mode** — `tinydb` is strictly an embedded
  library.

The audit log of scope checks is in `tests/scope_audit.md`.

---

## Architecture overview

`tinydb` is organised as five focused sub-packages:

| Layer | Module | Role |
|---|---|---|
| Storage | `tinydb.storage` | 4 KB-paged file I/O (`Pager`), LRU cache (`BufferPool`), row heap (`Heap`), schema catalog (`Catalog`) |
| Index | `tinydb.index` | B-tree implementation + `IndexManager` |
| SQL | `tinydb.sql` | Tokenizer + parser + AST |
| Executor | `tinydb.executor` | Plan tree, planner, DML / aggregation operators |
| Tx | `tinydb.tx` | `WriteLock`, `WAL`, `TransactionManager`, `Recovery`, `Checkpoint` |

The user-facing handle is `tinydb.Database` (or `tinydb.open(path)`),
which wires the layers together and exposes `execute(sql)` plus a
`transaction()` context manager.

---

## Running tests

```bash
python -m pytest tests/
```

The CI gate is:

```bash
python -m pytest tests/ --cov=src/tinydb --cov-fail-under=80 -q
```

Optional markers: `-m unit`, `-m integration`, `-m slow`, `-m crash`.

---

## License

MIT.

---

## Status

**v0.1.0** — alpha.  The full test suite is green and the public API
(`tinydb.open`, `Database.execute`, the CLI / REPL) is exercisable end
to end via `examples/demo.py`.  No API-stability commitment yet.