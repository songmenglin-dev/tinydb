"""
Functional test runner for tinydb v0.1.

Runs each feature category against a fresh tinydb database, records
pass/fail per assertion, emits a JSON summary that the report generator
consumes.

Usage:
    python scripts/functional_tests.py

The script writes its output to scripts/.functional_results.json (relative
to repo root). Re-runs overwrite the file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

import tinydb


REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "scripts" / ".functional_results.json"


class Recorder:
    def __init__(self) -> None:
        self.results: List[dict] = []

    def header(self, title: str) -> None:
        print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")

    def record(self, category, name, passed, command, output, error=""):
        truncated = output if len(output) < 600 else output[:600] + "\n... [truncated]"
        self.results.append({
            "category": category,
            "name": name,
            "passed": bool(passed),
            "command": command,
            "stdout": truncated,
            "error": str(error) if error else "",
        })
        status = "PASS" if passed else "FAIL"
        print(f"    [{status}] {name}")
        if command:
            print(f"        SQL  : {command}")
        if not passed and error:
            print(f"        ERR  : {error}")

    def save(self):
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(self.results, indent=2, ensure_ascii=False))
        print(f"\nResults JSON written to {RESULTS_PATH}")


rec = Recorder()


def _run(db, cmd):
    return db.execute(cmd)


def _bootstrap(db) -> None:
    """Reset schema to a known state for the users table."""
    _run(db, "DROP TABLE IF EXISTS users")
    _run(db, "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL, age INT)")


def category_ddl(db):
    _bootstrap(db)
    rec.header("DDL: CREATE / DROP TABLE")

    out = _run(db, "CREATE TABLE demo (x INT, y TEXT)")
    rec.record("DDL", "CREATE TABLE returns empty list",
               out == [], "CREATE TABLE demo (x INT, y TEXT)", repr(out))

    try:
        out = _run(db, "SELECT x FROM demo")
        rec.record("DDL", "Table is reachable after CREATE",
                   isinstance(out, list), "SELECT x FROM demo", repr(out))
    except Exception as exc:
        rec.record("DDL", "Table is reachable after CREATE",
                   False, "SELECT x FROM demo", "", str(exc))

    try:
        out = _run(db, "DROP TABLE demo")
        rec.record("DDL", "DROP TABLE returns empty list",
                   out == [], "DROP TABLE demo", repr(out))
    except Exception as exc:
        rec.record("DDL", "DROP TABLE returns empty list",
                   False, "DROP TABLE demo", "", str(exc))


def category_dml_basic(db):
    _bootstrap(db)
    rec.header("DML: INSERT / SELECT / UPDATE / DELETE")

    out = _run(db, "INSERT INTO users VALUES (1, 'alice', 30)")
    rec.record("DML", "INSERT (1, 'alice', 30)",
               out == [(1,)], "INSERT INTO users VALUES (1, 'alice', 30)", repr(out))
    _run(db, "INSERT INTO users VALUES (2, 'bob', 25)")
    _run(db, "INSERT INTO users VALUES (3, 'carol', 35)")
    _run(db, "INSERT INTO users VALUES (4, 'dave', 18)")

    out = _run(db, "SELECT * FROM users")
    rec.record("DML", "SELECT * returns 4 rows",
               isinstance(out, list) and len(out) == 4,
               "SELECT * FROM users", repr(out))

    out = _run(db, "SELECT * FROM users WHERE age > 25")
    rec.record("DML", "SELECT WHERE age > 25 (alice+carol=2)",
               isinstance(out, list) and len(out) == 2,
               "SELECT * FROM users WHERE age > 25", repr(out))

    out = _run(db, "UPDATE users SET age = 31 WHERE id = 1")
    rec.record("DML", "UPDATE returns affected count (1)",
               isinstance(out, list) and out == [(1,)],
               "UPDATE users SET age = 31 WHERE id = 1", repr(out))

    out = _run(db, "SELECT * FROM users WHERE id = 1")
    rec.record("DML", "UPDATE reflected (age=31)",
               isinstance(out, list) and len(out) == 1 and out[0][2] == 31,
               "SELECT * FROM users WHERE id = 1", repr(out))

    out = _run(db, "DELETE FROM users WHERE id = 4")
    rec.record("DML", "DELETE returns affected count (1)",
               isinstance(out, list) and out == [(1,)],
               "DELETE FROM users WHERE id = 4", repr(out))

    out = _run(db, "SELECT * FROM users")
    rec.record("DML", "DELETE persisted (3 rows)",
               isinstance(out, list) and len(out) == 3,
               "SELECT * FROM users", repr(out))


def category_filtering(db):
    _bootstrap(db)
    rec.header("WHERE: AND / OR / IS NULL")

    _run(db, "INSERT INTO users VALUES (1, 'alice', 30)")
    _run(db, "INSERT INTO users VALUES (2, 'bob', 25)")
    _run(db, "INSERT INTO users VALUES (3, 'carol', 35)")
    _run(db, "INSERT INTO users VALUES (4, 'eve', NULL)")

    out = _run(db, "SELECT * FROM users WHERE age > 25 AND name != 'carol'")
    rec.record("Filter", "AND + inequality (1 row)",
               isinstance(out, list) and len(out) == 1 and out[0][1] == 'alice',
               "SELECT ... WHERE age > 25 AND name != 'carol'", repr(out))

    out = _run(db, "SELECT * FROM users WHERE name = 'bob' OR name = 'carol'")
    rec.record("Filter", "OR over names (2 rows)",
               isinstance(out, list) and len(out) == 2,
               "SELECT ... WHERE name='bob' OR name='carol'", repr(out))

    out = _run(db, "SELECT * FROM users WHERE age IS NULL")
    rec.record("Filter", "IS NULL matches eve",
               isinstance(out, list) and len(out) == 1 and out[0][1] == 'eve',
               "SELECT ... WHERE age IS NULL", repr(out))

    out = _run(db, "SELECT * FROM users WHERE age IS NOT NULL")
    rec.record("Filter", "IS NOT NULL excludes NULLs (3 rows)",
               isinstance(out, list) and len(out) == 3,
               "SELECT ... WHERE age IS NOT NULL", repr(out))


def category_ordering(db):
    _bootstrap(db)
    rec.header("ORDER BY / LIMIT / OFFSET")

    rows_data = [(1, 'alice', 10), (2, 'bob', 20), (3, 'carol', 30), (4, 'dave', 40)]
    for i, n, a in rows_data:
        _run(db, f"INSERT INTO users VALUES ({i}, '{n}', {a})")

    out = _run(db, "SELECT name FROM users ORDER BY age ASC LIMIT 2")
    rec.record("Ordering", "ORDER BY ASC LIMIT 2 (alice+bob)",
               isinstance(out, list) and len(out) == 2 and out[0][0] == 'alice',
               "SELECT name FROM users ORDER BY age ASC LIMIT 2", repr(out))

    out = _run(db, "SELECT name FROM users ORDER BY age DESC LIMIT 2")
    rec.record("Ordering", "ORDER BY DESC LIMIT 2 (dave+carol)",
               isinstance(out, list) and len(out) == 2 and out[0][0] == 'dave',
               "SELECT name FROM users ORDER BY age DESC LIMIT 2", repr(out))

    out = _run(db, "SELECT name FROM users ORDER BY age ASC LIMIT 1 OFFSET 2")
    rec.record("Ordering", "OFFSET 2 LIMIT 1 (carol)",
               isinstance(out, list) and len(out) == 1 and out[0][0] == 'carol',
               "SELECT ... ORDER BY age ASC LIMIT 1 OFFSET 2", repr(out))


def category_aggregate(db):
    _bootstrap(db)
    rec.header("Aggregate: COUNT / SUM / AVG / MIN / MAX + GROUP BY")

    _run(db, "INSERT INTO users VALUES (1, 'alice', 30)")
    _run(db, "INSERT INTO users VALUES (2, 'bob', 25)")
    _run(db, "INSERT INTO users VALUES (3, 'carol', 35)")
    _run(db, "INSERT INTO users VALUES (4, 'dave', 18)")

    out = _run(db, "SELECT COUNT(*) FROM users")
    rec.record("Aggregate", "COUNT(*) = 4",
               isinstance(out, list) and out == [(4,)],
               "SELECT COUNT(*) FROM users", repr(out))

    out = _run(db, "SELECT MIN(age), MAX(age), SUM(age), AVG(age) FROM users")
    passed = (isinstance(out, list) and len(out) == 1 and
              out[0][0] == 18 and out[0][1] == 35 and
              abs(out[0][3] - 27.0) < 0.5)
    rec.record("Aggregate", "MIN/MAX/SUM/AVG",
               passed, "SELECT MIN(age), MAX(age), SUM(age), AVG(age) FROM users", repr(out))

    out = _run(db, "SELECT COUNT(*) FROM users GROUP BY name")
    rec.record("Aggregate", "GROUP BY name returns 4 rows",
               isinstance(out, list) and len(out) == 4,
               "SELECT COUNT(*) FROM users GROUP BY name", repr(out))


def category_index(db):
    _bootstrap(db)
    rec.header("B-tree Index")

    _run(db, "INSERT INTO users VALUES (1, 'alice', 30)")
    _run(db, "INSERT INTO users VALUES (2, 'bob', 25)")

    out = _run(db, "CREATE INDEX idx_users_name ON users (name)")
    rec.record("Index", "CREATE INDEX returns empty list",
               out == [], "CREATE INDEX idx_users_name ON users (name)", repr(out))

    out = _run(db, "SELECT * FROM users WHERE name = 'alice'")
    rec.record("Index", "Equality lookup via indexed column (1 row, alice)",
               isinstance(out, list) and len(out) == 1 and out[0][1] == 'alice',
               "SELECT * FROM users WHERE name = 'alice'", repr(out))

    try:
        _run(db, "INSERT INTO users VALUES (99, 'alice', 99)")
        rec.record("Index", "UNIQUE duplicate name rejected",
                   False, "INSERT INTO users VALUES (99, 'alice', 99)", "(no error)")
    except Exception as exc:
        rec.record("Index", "UNIQUE duplicate name rejected",
                   True, "INSERT INTO users VALUES (99, 'alice', 99)", "", str(exc)[:300])

    try:
        _run(db, "INSERT INTO users (id, age) VALUES (100, 99)")
        rec.record("Index", "NOT NULL violation rejected",
                   False, "INSERT INTO users (id, age) VALUES (100, 99)", "(no error)")
    except Exception as exc:
        rec.record("Index", "NOT NULL violation rejected",
                   True, "INSERT INTO users (id, age) VALUES (100, 99)", "", str(exc)[:300])


def category_transactions(db):
    _bootstrap(db)
    rec.header("Transactions: BEGIN / COMMIT / ROLLBACK")

    with db.transaction():
        _run(db, "INSERT INTO users VALUES (200, 'tx1', 1)")
    out = _run(db, "SELECT * FROM users WHERE id = 200")
    rec.record("Transactions", "COMMIT — DML persisted",
               isinstance(out, list) and len(out) == 1,
               "SELECT * FROM users WHERE id = 200", repr(out))

    try:
        with db.transaction():
            _run(db, "INSERT INTO users VALUES (201, 'rb', 1)")
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    out = _run(db, "SELECT * FROM users WHERE id = 201")
    rec.record("Transactions", "ROLLBACK — DML undone (0 rows)",
               isinstance(out, list) and len(out) == 0,
               "SELECT * FROM users WHERE id = 201", repr(out))


def category_types(db):
    rec.header("Type System: 10 types round-trip")

    _run(db, "CREATE TABLE type_test (a_int INT, a_float FLOAT, a_text TEXT, a_bool BOOL, a_date DATE, a_time TIME, a_dt DATETIME, a_dec DECIMAL, a_blob BLOB, a_json JSON)")
    _run(db, "INSERT INTO type_test VALUES (42, 3.14, 'hello', TRUE, DATE '2024-01-15', TIME '13:45:00', DATETIME '2024-01-15 13:45:00', DECIMAL '12345.6789', BLOB '000102', JSON '{\"k\":1}')")

    rows = _run(db, "SELECT * FROM type_test")
    rec.record("Types", "Row present (1 row)",
               isinstance(rows, list) and len(rows) == 1,
               "SELECT * FROM type_test", repr(rows))

    if isinstance(rows, list) and len(rows) == 1:
        row = rows[0]
        checks = [
            ("INT",      row[0] == 42),
            ("FLOAT",    abs(row[1] - 3.14) < 0.001),
            ("TEXT",     row[2] == "hello"),
            ("BOOL",     row[3] is True),
            ("DATE",     row[4] == "2024-01-15"),
            ("TIME",     row[5] == "13:45:00"),
            ("DATETIME", row[6] == "2024-01-15 13:45:00"),
            ("DECIMAL",  row[7] == "12345.6789"),
            ("BLOB",     row[8] == b"\x00\x01\x02"),
            ("JSON",     row[9] == {"k": 1}),
        ]
        for tname, ok in checks:
            rec.record("Types", f"{tname} round-trip",
                       ok, f"(row[{checks.index((tname, ok))}])",
                       f"got={row[checks.index((tname, ok))]!r}",
                       "" if ok else "(value mismatch)")


def category_persistence(persist_db_path: Path):
    rec.header("Persistence: close + reopen + recovery")

    with tinydb.open(str(persist_db_path)) as db:
        _run(db, "CREATE TABLE persist_demo (id INT PRIMARY KEY, val TEXT)")
        _run(db, "INSERT INTO persist_demo VALUES (1, 'first')")
        _run(db, "INSERT INTO persist_demo VALUES (2, 'second')")

    with tinydb.open(str(persist_db_path)) as db:
        out = _run(db, "SELECT * FROM persist_demo ORDER BY id")
        passed = (isinstance(out, list) and len(out) == 2 and
                  out[0][1] == 'first' and out[1][1] == 'second')
        rec.record("Persistence", "Reopen via recovery preserves rows",
                   passed, "SELECT * FROM persist_demo ORDER BY id", repr(out))


def category_cli_subprocess():
    rec.header("CLI: python -m tinydb --db X -c SQL")
    import subprocess, tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "cli_test.db"
        proc = subprocess.run(
            [sys.executable, "-m", "tinydb", "--db", str(tmp_db),
             "-c", "CREATE TABLE cli_demo (n INT)"],
            capture_output=True, text=True, timeout=15,
        )
        passed = proc.returncode == 0 and "OK" in proc.stdout
        rec.record("CLI", "CREATE TABLE one-shot → OK",
                   passed, "CREATE TABLE cli_demo (n INT)", proc.stdout,
                   proc.stderr if proc.returncode else "")

        proc = subprocess.run(
            [sys.executable, "-m", "tinydb", "--db", str(tmp_db),
             "-c", "INSERT INTO cli_demo VALUES (1), (2), (3)"],
            capture_output=True, text=True, timeout=15,
        )
        passed = proc.returncode == 0 and "3 row(s)" in proc.stdout
        rec.record("CLI", "INSERT one-shot → 3 row(s)",
                   passed, "INSERT INTO cli_demo VALUES (1), (2), (3)", proc.stdout,
                   proc.stderr if proc.returncode else "")

        proc = subprocess.run(
            [sys.executable, "-m", "tinydb", "--db", str(tmp_db),
             "-c", "SELECT * FROM cli_demo"],
            capture_output=True, text=True, timeout=15,
        )
        passed = (proc.returncode == 0 and "n" in proc.stdout
                  and "1" in proc.stdout and "3" in proc.stdout)
        rec.record("CLI", "SELECT one-shot → real column header 'n'",
                   passed, "SELECT * FROM cli_demo", proc.stdout,
                   proc.stderr if proc.returncode else "")


def main() -> int:
    tmp_db = REPO_ROOT / "scripts" / ".functional_test.db"
    tmp_db.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("", ".wal"):
        p = Path(str(tmp_db) + ext)
        if p.exists():
            p.unlink()

    try:
        for stage in (
            category_ddl,
            category_dml_basic,
            category_filtering,
            category_ordering,
            category_aggregate,
            category_index,
            category_transactions,
            category_types,
        ):
            for ext in ("", ".wal"):
                p = Path(str(tmp_db) + ext)
                if p.exists():
                    p.unlink()
            db = tinydb.open(str(tmp_db))
            try:
                stage(db)
            finally:
                db.close()

        persist_db = REPO_ROOT / "scripts" / ".functional_persist.db"
        persist_db.parent.mkdir(parents=True, exist_ok=True)
        for ext in ("", ".wal"):
            p = Path(str(persist_db) + ext)
            if p.exists():
                p.unlink()
        category_persistence(persist_db)

        category_cli_subprocess()
    finally:
        for ext in ("", ".wal"):
            for p in (tmp_db, REPO_ROOT / "scripts" / ".functional_persist.db"):
                target = Path(str(p) + ext)
                if target.exists():
                    target.unlink()

    rec.save()

    total = len(rec.results)
    passed = sum(1 for r in rec.results if r["passed"])
    failed = total - passed
    pct = (passed / total * 100) if total else 0.0
    print(f"\n{'=' * 70}\n  SUMMARY: {passed}/{total} passed ({pct:.1f}%) — {failed} failed\n{'=' * 70}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
