# tinydb

> A pure-Python embedded relational database with SQL JOINs, concurrent
> access, and an interactive REPL — no third-party runtime dependencies.

`tinydb` is a tiny SQL engine that fits in one process.  It gives you
`CREATE TABLE` / `INSERT` / `SELECT` / `UPDATE` / `DELETE`, `INNER` /
`LEFT JOIN` with `ON` / `USING` and table aliases, transactional
multi-thread access with cross-process safety, a B-tree secondary index,
crash recovery, and an interactive REPL.

The whole stack — tokenizer, parser, planner, executor, B-tree,
heap, WAL, recovery, connection pool — lives in one package, every
layer is testable in isolation, and the runtime pulls **no
third-party packages**.

---

## Features

1. **SQL DDL + DML** — `CREATE TABLE`, `DROP TABLE`, `INSERT`, `SELECT`,
   `UPDATE`, `DELETE`, with `WHERE`, `ORDER BY`, `LIMIT`, `OFFSET`,
   `GROUP BY`, and the standard aggregations (`COUNT`, `SUM`, `AVG`,
   `MIN`, `MAX`).
2. **`INNER` and `LEFT JOIN`** with `ON` predicates and `USING(col)`
   column-list shorthand; table aliases (`FROM users u`) and qualified
   `alias.col` projection; `WHERE` is correctly applied after the join.
3. **Static type system** — `INT`, `FLOAT`, `TEXT`, `BOOL`, `DATE`,
   `TIME`, `DATETIME`, `DECIMAL`, `BLOB`, `JSON` with strict coercion.
4. **B-tree secondary indexes** — including composite-key indexes,
   auto-created unique indexes for `PRIMARY KEY`, and index-driven
   `IndexedNestedLoopJoin`.
5. **Concurrent access** — read/write `RWLock`, per-call process
   lock (`fcntl`), WAL append fsync, snapshot isolation
   (`READ COMMITTED`) and an opt-in `SERIALIZABLE` mode.
6. **Connection pool** — `Database(pool_size=N)` exposes
   `acquire` / `release` / `connection()` so multi-threaded callers can
   share one database file safely.
7. **Transactions (ACID)** — single-writer coordination, append-only
   `WAL`, `Recovery` (REDO/UNDO), periodic `Checkpoint`.
8. **Interactive CLI / REPL** — `prompt_toolkit`-powered REPL with
   history, syntax highlighting, multi-line continuation, and meta
   commands (`.tables`, `.schema`, `.explain`, `.history`, `.mode`).
9. **Crash safety** — committed transactions survive process exit and
   machine crash; uncommitted writes are rolled back on reopen.
10. **Zero runtime dependencies** — pure Python stdlib for the core;
    `prompt_toolkit` (optional, `[cli]` extra) only for the REPL.

---

## Install

`tinydb` runs straight from a source-tree checkout.  Clone the repo
and you can `import tinydb` directly:

```bash
git clone <repo-url> tinydb
cd tinydb
pip install -e ".[cli]"   # editable install; adds prompt_toolkit
python -c "import tinydb; print(tinydb.__version__)"
```

For tests:

```bash
pip install -e ".[cli,test]"
```

A release on PyPI is on the roadmap (DP-7); until then
`pip install -e .` is the canonical way to expose `tinydb` on your
`PYTHONPATH`.

---

## Quick Start

```python
import tinydb

with tinydb.open("/tmp/demo.db") as db:
    db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES (1, 'alice')")
    db.execute("INSERT INTO users VALUES (2, 'bob')")
    for row in db.execute("SELECT * FROM users"):
        print(row)
```

`db.execute(sql)` returns a `list[tuple]` for `SELECT`, a single
`[(affected_count,)]` row for DML, and `[]` for DDL.  Any failure
raises `tinydb.errors.TinydbError` (or a subclass).

### JOIN

```python
db.execute("CREATE TABLE orders (oid INT PRIMARY KEY, uid INT, total INT)")
db.execute("INSERT INTO orders VALUES (10, 1, 100), (11, 2, 50)")

rows = db.execute(
    "SELECT u.name, o.total "
    "FROM users u INNER JOIN orders o ON u.id = o.uid "
    "WHERE o.total > 60"
)
# [('alice', 100)]
```

`LEFT JOIN` keeps unmatched rows (`o.total` becomes `None`); `USING(col)`
collapses the join column by name; the planner picks `NestedLoopJoin` vs
`IndexedNestedLoopJoin` based on index availability.

### Concurrent threads

```python
import threading

db = tinydb.open("/tmp/demo.db", pool_size=8)

def writer(tid):
    with db.connection() as conn:
        conn.execute(f"INSERT INTO users VALUES ({tid}, 't{tid}')")

threads = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
for t in threads: t.start()
for t in threads: t.join()
```

`pool_size > 1` opts into the connection pool.  For cross-process
safety pass `use_process_lock=True` to the `Database` constructor.

---

## CLI / REPL

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
orders
tinydb> .schema users
CREATE TABLE users (id Int PRIMARY KEY, name Text NOT NULL);
tinydb> .explain SELECT u.name FROM users u JOIN orders o ON u.id = o.uid
LogicalPlan
└── Project(table=users, cols=[name])
    └── NestedLoopJoin(table=users, on=u.id = o.uid)
        ├── SeqScan(table=users)
        └── SeqScan(table=orders)
PhysicalPlan
└── Project(table=users, cols=[name])
    └── NestedLoopJoin(table=users, on=u.id = o.uid)
        ├── SeqScan(table=users)
        └── SeqScan(table=orders)
tinydb> .mode line
tinydb> SELECT COUNT(*) FROM users;
[1 tuple]
COUNT(*) = 2
tinydb> .exit
```

The REPL is line-oriented by default; `.mode table` switches to a
MySQL-style boxed grid, and `.mode line` reverts.  `.history` prints
your inputs (also persisted at `~/.tinydb_history`).  Multi-line
continuations are auto-detected for unbalanced parens / quotes.

Supported meta-commands: `.tables`, `.schema`, `.explain`, `.mode`,
`.history`, `.help`, `.exit` / `.quit`.  See `examples/demo_v0_2.py`
for a runnable end-to-end walkthrough.

---

## Database kwargs

```python
db = tinydb.open(
    path,
    *,                                # keyword-only
    isolation=tinydb.IsolationLevel.READ_COMMITTED,
    pool_size=1,                      # 1 preserves v0.1 single-conn fence
    use_process_lock=False,           # set True for cross-process safety
)
```

| Kwarg | Default | Effect |
|---|---|---|
| `isolation` | `READ_COMMITTED` | Each transaction captures a snapshot at BEGIN; pass `tinydb.IsolationLevel.SERIALIZABLE` for fully serialized reads. |
| `pool_size` | `1` | `>1` opts into a bounded FIFO connection pool. |
| `use_process_lock` | `False` | Adds an `fcntl`-based cross-process exclusive lock around writes. |

---

## Limitations / Out of Scope

These are deliberate omissions for v0.2; they are not bugs:

- **`RIGHT JOIN` and `FULL OUTER JOIN`** — only `INNER` and `LEFT`.
- **Subqueries / CTEs** — `SELECT` may not appear in a `WHERE` clause.
- **MVCC** — snapshots are `READ COMMITTED` style; `SERIALIZABLE` is
  implemented with a write-preferring RWLock rather than multi-version
  storage.
- **Triggers, stored procedures, foreign keys.**
- **`ALTER TABLE`** — schemas are immutable after `CREATE TABLE`.
- **Network / client-server mode** — `tinydb` is strictly an embedded
  library.

The audit log of scope checks is in `tests/scope_audit.md`.

---

## Architecture overview

`tinydb` is organised into focused sub-packages:

| Layer | Module | Role |
|---|---|---|
| Storage | `tinydb.storage` | 4 KB-paged file I/O (`Pager`), LRU cache (`BufferPool`), row heap (`Heap`), schema catalog (`Catalog`) |
| Index | `tinydb.index` | B-tree implementation + `IndexManager` |
| SQL | `tinydb.sql` | Tokenizer + parser + AST |
| Executor | `tinydb.executor` | `LogicalPlanner`, `PhysicalPlanner`, scan/filter/project/aggregate/join operators |
| Concurrent | `tinydb.concurrent` | `RWLock`, `DeadlockDetector`, `fcntl`-based `ProcessLock` |
| Tx | `tinydb.tx` | `WriteLock`, `WAL`, `Snapshot`, `TransactionManager`, `Recovery`, `Checkpoint` |
| CLI | `tinydb.cli` | `prompt_toolkit` REPL, MySQL-grid formatter, ASCII plan-tree renderer |
| Public API | `tinydb.api` | `Database`, `IsolationLevel`, `open(path)` |

The user-facing handle is `tinydb.Database` (or `tinydb.open(path)`),
which wires the layers together and exposes `execute(sql)`,
`explain(sql)`, `list_tables()`, `get_schema(name)`, plus a
`transaction()` context manager and an opt-in `acquire/release/
connection()` pool protocol.

---

## Running tests

```bash
# Core + CLI tests with coverage gate.
PYTHONPATH=src:. pytest tests/ --cov=src/tinydb --cov-fail-under=80 -q
```

The v0.2 release gates are:

1. Coverage ≥ 80% on `src/tinydb/`.
2. The v0.1 unit suite + CLI tests still pass under v0.2 code.
3. A 32-thread INSERT/SELECT stress test runs for 5 seconds without
   deadlock or lost inserts.
4. A multi-process (1 writer + 3 readers) test never observes a dirty
   read.

Optional markers: `-m unit`, `-m integration`, `-m slow`, `-m crash`.

A runnable end-to-end story lives in `examples/demo_v0_2.py`:

```bash
PYTHONPATH=src python examples/demo_v0_2.py
```

---

## License

MIT.

---

## Status

**v0.2.0** — beta.  The full test suite is green; `JOIN`, `connection
pool`, `RWLock`, `WAL`, `Recovery`, and the `prompt_toolkit`-powered
REPL are all public and documented.  The CLI is intentionally
lightweight; richer tooling (transactions UI, EXPLAIN ANALYZE,
prepared statements) is on the post-v0.2 roadmap.  No API-stability
commitment yet.
