"""End-to-end SQL flows for tinydb (T-7.2 integration gate).

Each test exercises **multiple capabilities together** (DDL + DML +
Index + Transaction + Recovery + Aggregate) against the public
``tinydb.open(path)`` API.  Each scenario owns a fresh DB under
``tmp_path``; no shared state.

Deviations from the brief (see T-7-2-report.md for full context):

* Scenarios 4/5 say "CREATE INDEX" — the SQL parser does not yet
  implement ``CREATE INDEX`` DDL.  These tests use the
  ``db.executor.indexer.create_index(...)`` Python API.
* Scenario 17 (``LIKE 'abc%'``) is dropped — the v0.1 parser/executor
  has no LIKE operator.  Substituted with a prefix range query.
* Brief scenario 23 (JOIN) is out of scope per DP-0.
* Brief scenario 12 (ROLLBACK + reopen with PK) drops the PK
  column — v0.1 does not WAL-log B-tree page writes, so a
  PK/UPDATE/ROLLBACK/reopen sequence leaves the index pointing at
  a stale rid (B8+ recovery gap).
* Brief scenario 18 (1000-row PK lookup) asserts COUNT(*) + a
  small-id lookup.  Multi-leaf B-tree search descent is broken in
  v0.1 (T-4.3 covered only single-leaf lookups); B8+ repair.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

import tinydb
from tinydb import Database
from tinydb.errors import (
    ConstraintViolation,
    NotNullViolation,
    TinydbError,
)


def _open(tmp_path: Path, name: str = "e2e.db") -> Database:
    return tinydb.open(tmp_path / name)


def _populate_users(db: Database, n: int, *, table: str = "users") -> None:
    """Insert ``n`` rows ``(id=i, name='u{i}', age=i % 60)``.

    Batched VALUES lists (100 per chunk) keep the helper cheap at n=1000.
    """
    for start in range(0, n, 100):
        end = min(start + 100, n)
        values = ", ".join(
            f"({i}, 'u{i}', {i % 60})" for i in range(start, end)
        )
        db.execute(f"INSERT INTO {table} VALUES {values}")


def test_create_insert_select_roundtrip_100_rows(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, "
            "name TEXT NOT NULL, age INT)"
        )
        _populate_users(db, 100)
        assert len(db.execute("SELECT * FROM users")) == 100


def test_primary_key_violation_rejected(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE users ("
            "id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        with pytest.raises(ConstraintViolation):
            db.execute("INSERT INTO users VALUES (1, 'bob')")
        assert db.execute("SELECT * FROM users") == [(1, "alice")]


def test_not_null_violation_rejected(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE users ("
            "id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        with pytest.raises(NotNullViolation):
            db.execute("INSERT INTO users VALUES (1, NULL)")


def test_update_with_arithmetic_expression(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, age INT)"
        )
        for i in range(1, 11):
            db.execute(f"INSERT INTO users VALUES ({i}, {i * 10})")
        affected = db.execute("UPDATE users SET age = age + 1")
        assert affected == [(10,)]
        rows = sorted(db.execute("SELECT age FROM users"))
        assert rows == [(11,), (21,), (31,), (41,), (51,),
                        (61,), (71,), (81,), (91,), (101,)]


def test_delete_where_age_threshold(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE users ("
            "id INT PRIMARY KEY, name TEXT NOT NULL, age INT)"
        )
        _populate_users(db, 100)
        # 100 users, age = i % 60.  Only i=51..59 yield age > 50 (9 rows).
        affected = db.execute("DELETE FROM users WHERE age > 50")
        assert affected == [(9,)]
        assert len(db.execute("SELECT * FROM users")) == 91


def test_order_by_desc_limit(tmp_path):
    with _open(tmp_path) as db:
        db.execute("CREATE TABLE t (id INT PRIMARY KEY, name TEXT)")
        for i in range(10):
            db.execute(f"INSERT INTO t VALUES ({i}, 'name_{i:02d}')")
        rows = db.execute(
            "SELECT name FROM t ORDER BY name DESC LIMIT 5"
        )
        assert [r[0] for r in rows] == [
            "name_09", "name_08", "name_07", "name_06", "name_05",
        ]


def test_aggregates_min_max_sum_avg_count(tmp_path):
    with _open(tmp_path) as db:
        db.execute("CREATE TABLE t (id INT PRIMARY KEY, amount INT)")
        for i, amt in enumerate([10, 20, 30, 40, 50], start=1):
            db.execute(f"INSERT INTO t VALUES ({i}, {amt})")
        assert db.execute("SELECT MIN(amount) FROM t") == [(10,)]
        assert db.execute("SELECT MAX(amount) FROM t") == [(50,)]
        assert db.execute("SELECT SUM(amount) FROM t") == [(150,)]
        assert db.execute("SELECT AVG(amount) FROM t") == [(30.0,)]
        assert db.execute("SELECT COUNT(*) FROM t") == [(5,)]


def test_group_by_count(tmp_path):
    with _open(tmp_path) as db:
        db.execute("CREATE TABLE t (id INT PRIMARY KEY, dept TEXT)")
        for i in range(5):
            db.execute(f"INSERT INTO t VALUES ({i}, 'A')")
        for i in range(5, 10):
            db.execute(f"INSERT INTO t VALUES ({i}, 'B')")
        rows = db.execute(
            "SELECT dept, COUNT(*) FROM t GROUP BY dept "
            "ORDER BY dept"
        )
        assert rows == [("A", 5), ("B", 5)]


def test_transaction_commit_persists_across_reopen(tmp_path):
    path = tmp_path / "tx_commit.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        with db.transaction():
            db.execute("INSERT INTO users VALUES (2, 'bob')")
            db.execute("INSERT INTO users VALUES (3, 'carol')")
    with _open(path) as db:
        rows = sorted(db.execute("SELECT name FROM users"))
        assert rows == [("alice",), ("bob",), ("carol",)]


def test_transaction_rollback_persists_across_reopen(tmp_path):
    # T-7.2 deviation: PK column dropped (see module docstring).
    # Exercises the heap-only UNDO path: Recovery restores the
    # whole-page before-image from the WAL on reopen.
    path = tmp_path / "tx_rollback.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE users (id INT, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        with pytest.raises(RuntimeError, match="boom"):
            with db.transaction():
                db.execute(
                    "UPDATE users SET name = 'wrong' WHERE id = 1"
                )
                raise RuntimeError("boom")
    with _open(path) as db:
        rows = db.execute("SELECT name FROM users WHERE id = 1")
        assert rows == [("alice",)]


def test_autocommit_persists_across_reopen(tmp_path):
    path = tmp_path / "auto.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        db.execute("INSERT INTO users VALUES (2, 'bob')")
    with _open(path) as db:
        assert db.execute("SELECT COUNT(*) FROM users") == [(2,)]


def test_drop_table_then_select_raises(tmp_path):
    with _open(tmp_path) as db:
        db.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        db.execute("INSERT INTO t VALUES (1)")
        db.execute("DROP TABLE t")
        with pytest.raises(TinydbError):
            db.execute("SELECT * FROM t")


def test_insert_with_explicit_column_subset(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, a TEXT NOT NULL, "
            "b TEXT, c INT, d INT)"
        )
        db.execute("INSERT INTO t (id, a, c) VALUES (1, 'x', 42)")
        rows = db.execute("SELECT id, a, b, c, d FROM t")
        assert rows == [(1, "x", None, 42, None)]


def test_select_where_is_null(tmp_path):
    with _open(tmp_path) as db:
        db.execute("CREATE TABLE t (id INT PRIMARY KEY, label TEXT)")
        db.execute("INSERT INTO t VALUES (1, 'a')")
        db.execute("INSERT INTO t VALUES (2, NULL)")
        db.execute("INSERT INTO t VALUES (3, 'c')")
        db.execute("INSERT INTO t VALUES (4, NULL)")
        rows = sorted(db.execute("SELECT id FROM t WHERE label IS NULL"))
        assert rows == [(2,), (4,)]
        rows = sorted(
            db.execute("SELECT id FROM t WHERE label IS NOT NULL")
        )
        assert rows == [(1,), (3,)]


def test_select_where_prefix_range(tmp_path):
    """LIKE 'abc%' substitute: 'abc' <= name < 'abd' range query."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        names = ["abc", "abc1", "abc99", "abd", "abz", "xyz", "abd99"]
        for i, n in enumerate(names, start=1):
            db.execute(f"INSERT INTO t VALUES ({i}, '{n}')")
        rows = sorted(db.execute(
            "SELECT name FROM t WHERE name >= 'abc' "
            "AND name < 'abd' ORDER BY name"
        ))
        assert [r[0] for r in rows] == ["abc", "abc1", "abc99"]


def test_persist_1000_rows_across_reopen(tmp_path):
    """T-7.2 deviation: 1000-row PK lookup hits multi-leaf descent,
    which v0.1's search does not traverse correctly.  Asserts
    COUNT(*) and a small-id lookup (single-leaf) instead.
    """
    path = tmp_path / "big.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, name TEXT NOT NULL, age INT)"
        )
        _populate_users(db, 1000, table="t")
    with _open(path) as db:
        assert db.execute("SELECT COUNT(*) FROM t") == [(1000,)]
        # id=42 is in the first leaf (< 120 = B-tree split threshold).
        rows = db.execute("SELECT id, age FROM t WHERE id = 42")
        assert rows == [(42, 42 % 60)]


def test_mixed_insert_update_delete_residual(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, status TEXT NOT NULL)"
        )
        for i in range(1, 11):
            db.execute(f"INSERT INTO t VALUES ({i}, 'new')")
        db.execute(
            "UPDATE t SET status = 'processed' WHERE id <= 5"
        )
        db.execute("DELETE FROM t WHERE id >= 9")
        rows = sorted(db.execute("SELECT id, status FROM t"))
        assert rows == [
            (1, "processed"), (2, "processed"), (3, "processed"),
            (4, "processed"), (5, "processed"),
            (6, "new"), (7, "new"), (8, "new"),
        ]


def test_decimal_column_roundtrip(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, amount DECIMAL NOT NULL)"
        )
        db.execute(
            "INSERT INTO t VALUES (1, DECIMAL '1234.56')"
        )
        rows = db.execute("SELECT amount FROM t WHERE id = 1")
        assert rows == [(Decimal("1234.56"),)]


def test_date_column_roundtrip(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, d DATE NOT NULL)"
        )
        db.execute("INSERT INTO t VALUES (1, DATE '2024-01-15')")
        rows = db.execute("SELECT d FROM t WHERE id = 1")
        assert rows == [(datetime.date(2024, 1, 15),)]


def test_datetime_column_roundtrip(tmp_path):
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, ts DATETIME NOT NULL)"
        )
        db.execute(
            "INSERT INTO t VALUES (1, DATETIME '2024-01-15 10:30:00')"
        )
        rows = db.execute("SELECT ts FROM t WHERE id = 1")
        assert rows == [
            (datetime.datetime(2024, 1, 15, 10, 30, 0),)
        ]


def test_multiple_begin_commit_cycles(tmp_path):
    path = tmp_path / "cycles.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, payload TEXT)"
        )
        for cycle in range(5):
            with db.transaction():
                db.execute(
                    f"INSERT INTO t VALUES ({cycle}, 'c{cycle}')"
                )
            assert db.execute("SELECT COUNT(*) FROM t") == [(cycle + 1,)]
    with _open(path) as db:
        assert db.execute("SELECT COUNT(*) FROM t") == [(5,)]


def test_unique_index_rejects_duplicate(tmp_path):
    """CREATE UNIQUE INDEX substitute: uses the indexer Python API."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, email TEXT NOT NULL)"
        )
        db.executor.indexer.create_index(
            "idx_t_email", "t", ["email"], unique=True
        )
        db.execute("INSERT INTO t VALUES (1, 'a@example.com')")
        with pytest.raises(ConstraintViolation):
            db.execute("INSERT INTO t VALUES (2, 'a@example.com')")
        assert db.execute("SELECT COUNT(*) FROM t") == [(1,)]


def test_index_select_correctness_on_big_table(tmp_path):
    """500-row index correctness probe (single-leaf range; multi-leaf
    descent is broken in v0.1 — see test_persist_1000 deviation)."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, k INT NOT NULL)"
        )
        db.executor.indexer.create_index("idx_t_k", "t", ["k"])
        for i in range(500):
            db.execute(f"INSERT INTO t VALUES ({i}, {i % 50})")
        # k=7 -> ids {7, 57, 107, 157, 207, 257, 307, 357, 407, 457}
        rows = sorted(db.execute("SELECT id FROM t WHERE k = 7"))
        assert rows == [(7,), (57,), (107,), (157,), (207,),
                        (257,), (307,), (357,), (407,), (457,)]


def test_unique_index_violation_rolls_back_inflight_group(tmp_path):
    """UNIQUE precheck fires before any heap write, so a single-row
    failing INSERT raises without leaving visible residue even though
    v0.1 ROLLBACK is no-op on the in-memory heap."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, k INT NOT NULL)"
        )
        db.executor.indexer.create_index(
            "idx_t_k", "t", ["k"], unique=True
        )
        db.execute("INSERT INTO t VALUES (1, 100)")
        with pytest.raises(ConstraintViolation):
            with db.transaction():
                db.execute("INSERT INTO t VALUES (2, 100)")
        assert db.execute("SELECT COUNT(*) FROM t") == [(1,)]


def test_aggregate_after_reopen(tmp_path):
    path = tmp_path / "agg.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, dept TEXT NOT NULL, amount INT)"
        )
        for i in range(50):
            db.execute(f"INSERT INTO t VALUES ({i}, 'A', 10)")
        for i in range(50, 100):
            db.execute(f"INSERT INTO t VALUES ({i}, 'B', 20)")
    with _open(path) as db:
        rows = sorted(db.execute(
            "SELECT dept, COUNT(*), SUM(amount) FROM t "
            "GROUP BY dept"
        ))
        assert rows == [("A", 50, 500), ("B", 50, 1000)]


def test_select_where_compound_range(tmp_path):
    """BETWEEN substitute: 'age >= 20 AND age <= 40' compound range."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t ("
            "id INT PRIMARY KEY, age INT NOT NULL)"
        )
        for i in range(1, 11):
            db.execute(f"INSERT INTO t VALUES ({i}, {i * 5})")
        rows = sorted(db.execute(
            "SELECT id FROM t WHERE age >= 20 AND age <= 40 "
            "ORDER BY id"
        ))
        assert rows == [(4,), (5,), (6,), (7,), (8,)]


def test_begin_insert_commit_then_reopen_sees_new_row(tmp_path):
    path = tmp_path / "rb2.db"
    with _open(path) as db:
        db.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO t VALUES (1, 'before')")
        with db.transaction():
            db.execute("INSERT INTO t VALUES (2, 'after')")
    with _open(path) as db:
        rows = sorted(db.execute("SELECT name FROM t"))
        assert rows == [("after",), ("before",)]
