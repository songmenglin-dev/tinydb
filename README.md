# tinydb

> **Status:** 0.1.0-alpha — under active development.

A lightweight embedded relational database for Python.

`tinydb` is a from-scratch implementation designed to be both **readable**
(good for learning how an RDB works under the hood) and **practical** for
small projects. It is a single-file `.db` format with a pure SQL string
interface, ACID transactions, B-tree indexes, and an interactive REPL.

## Goals

- Pure SQL string interface: `db.execute("SELECT ...")`
- DDL / DML, WHERE / ORDER BY / LIMIT / GROUP BY
- 10 column types: `INT`, `FLOAT`, `TEXT`, `BOOL`, `DATE`, `TIME`,
  `DATETIME`, `DECIMAL`, `BLOB`, `JSON`
- B-tree index, ACID transactions (WAL + crash recovery)
- Single-file persistence with a 4KB paged storage engine
- Interactive REPL
- **Zero runtime dependencies** (Python stdlib only)

## Out of scope (v0.1.0)

Multi-table `JOIN`, multi-thread / multi-process concurrency, `ALTER
TABLE` / views / triggers / foreign keys, and client–server networking.
See `proposal.md` for the full scope statement.

## Quick start

```python
import tinydb

db = tinydb.open("data.db")
db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)")
db.execute("INSERT INTO users VALUES (1, 'alice')")
print(db.execute("SELECT * FROM users"))
# [{'id': 1, 'name': 'alice'}]
db.close()
```

## REPL

```bash
tinydb data.db
tinydb> CREATE TABLE t (id INT PRIMARY KEY, n TEXT);
tinydb> INSERT INTO t VALUES (1, 'hi');
tinydb> SELECT * FROM t;
┌────┬─────┐
│ id │  n  │
├────┼─────┤
│  1 │ hi  │
└────┴─────┘
1 row.
tinydb> .exit
```

## Installation

```bash
pip install -e .
```

## Testing

```bash
pytest --cov=src/tinydb --cov-fail-under=80
```

## License

MIT.
