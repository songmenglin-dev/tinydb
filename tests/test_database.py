"""Tests for the public Database facade (T-7.1).

Covers:
  1. context-manager close (auto-close on exit)
  2. CREATE TABLE -> columns visible via db.catalog
  3. INSERT + SELECT round-trip
  4. SELECT with WHERE filter
  5. UPDATE + SELECT (read-after-write within same connection)
  6. DELETE + SELECT (row gone)
  7. `with db.transaction():` commits cleanly; SELECT reflects the change
  8. Exception inside `with db.transaction():` -> ROLLBACK;
     the lock is released and the durable no-change contract holds
     across reopen (Recovery UNDO).
  9. DDL + INSERT + SELECT across multiple connections (close + reopen)
 10. invalid SQL raises ParseError
 11. `tinydb.open(path)` returns a Database
 12. `tinydb.Database` and `tinydb.open` are exposed in the public surface
"""

from __future__ import annotations

import pytest

import tinydb
from tinydb import Database, open as tinydb_open
from tinydb.errors import ParseError, TinydbError
from tinydb.storage.catalog import TableMeta
from tinydb.storage.pager import Pager


def _mk_db(tmp_path, name: str = "test.db") -> Database:
    """Create a Database attached to a fresh file under tmp_path."""
    return tinydb.open(tmp_path / name)


# ---------------------------------------------------------------------------
# 1. context-manager close
# ---------------------------------------------------------------------------


def test_context_manager_closes_pager(tmp_path):
    path = tmp_path / "ctx.db"
    with tinydb.open(path) as db:
        # pre-close: pager is reachable
        assert isinstance(db.pager, Pager)
        assert db._pager._closed is False
    # post-exit: pager is closed (private attr used to verify cleanup)
    assert path.exists()
    assert db._pager._closed is True


def test_context_manager_closes_wal(tmp_path):
    path = tmp_path / "ctxwal.db"
    with tinydb.open(path) as db:
        assert db._wal._closed is False
    assert db._wal._closed is True


def test_close_is_idempotent(tmp_path):
    db = tinydb.open(tmp_path / "idem.db")
    db.close()
    # Calling close twice must not raise.
    db.close()


# ---------------------------------------------------------------------------
# 2. CREATE TABLE -> catalog
# ---------------------------------------------------------------------------


def test_create_table_columns_visible_via_catalog(tmp_path):
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        meta = db.catalog.get_table("users")
        assert isinstance(meta, TableMeta)
        names = [c.name for c in meta.columns]
        assert names == ["id", "name"]
        assert meta.columns[0].primary_key is True
        assert meta.columns[1].not_null is True


# ---------------------------------------------------------------------------
# 3. INSERT + SELECT round-trip
# ---------------------------------------------------------------------------


def test_insert_select_roundtrip(tmp_path):
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        result = db.execute("INSERT INTO users VALUES (1, 'alice')")
        # DML returns [(affected_count,)]
        assert result == [(1,)]
        rows = db.execute("SELECT * FROM users")
        assert rows == [(1, "alice")]


# ---------------------------------------------------------------------------
# 4. SELECT with WHERE filter
# ---------------------------------------------------------------------------


def test_select_with_where(tmp_path):
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        db.execute("INSERT INTO users VALUES (2, 'bob')")
        rows = db.execute("SELECT * FROM users WHERE id = 2")
        assert rows == [(2, "bob")]


# ---------------------------------------------------------------------------
# 5. UPDATE + SELECT (read-after-write)
# ---------------------------------------------------------------------------


def test_update_then_select(tmp_path):
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        upd = db.execute("UPDATE users SET name = 'alice2' WHERE id = 1")
        assert upd == [(1,)]
        rows = db.execute("SELECT * FROM users WHERE id = 1")
        assert rows == [(1, "alice2")]


# ---------------------------------------------------------------------------
# 6. DELETE + SELECT (row gone)
# ---------------------------------------------------------------------------


def test_delete_then_select(tmp_path):
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        db.execute("INSERT INTO users VALUES (2, 'bob')")
        rem = db.execute("DELETE FROM users WHERE id = 1")
        assert rem == [(1,)]
        rows = db.execute("SELECT * FROM users")
        assert rows == [(2, "bob")]


# ---------------------------------------------------------------------------
# 7. transaction() commits cleanly
# ---------------------------------------------------------------------------


def test_transaction_commit(tmp_path):
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        with db.transaction() as tx:
            assert tx.tx_id >= 1
            db.execute("INSERT INTO users VALUES (1, 'alice')")
        # After clean exit, the row should be visible.
        rows = db.execute("SELECT * FROM users")
        assert rows == [(1, "alice")]


# ---------------------------------------------------------------------------
# 8. transaction() rollback on exception
# ---------------------------------------------------------------------------


def test_transaction_rollback_releases_lock(tmp_path):
    """An exception inside `with db.transaction():` rolls the tx back.

    v0.1 simplification (see `TransactionManager.rollback` docstring):
    in-memory state is NOT restored by ROLLBACK; the WAL + Recovery on
    next open is the durable contract.  What we DO guarantee in this
    test:

    * the exception propagates,
    * the write lock is released (a follow-up tx can begin cleanly).
    """
    with _mk_db(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        with pytest.raises(RuntimeError, match="boom"):
            with db.transaction():
                db.execute("UPDATE users SET name = 'wrong' WHERE id = 1")
                raise RuntimeError("boom")
        # Lock released -> a follow-up tx can begin.
        with db.transaction():
            db.execute("INSERT INTO users VALUES (2, 'bob')")
        rows = db.execute("SELECT * FROM users")
        assert (2, "bob") in rows


def test_rollback_durability_across_reopen(tmp_path):
    """A rolled-back UPDATE is undone on reopen (Recovery UNDO)."""
    path = tmp_path / "rb.db"
    with tinydb.open(path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        with pytest.raises(RuntimeError):
            with db.transaction():
                db.execute("UPDATE users SET name = 'wrong' WHERE id = 1")
                raise RuntimeError("boom")
    # Reopen -- Recovery undoes the uncommitted UPDATE.
    with tinydb.open(path) as db:
        rows = db.execute("SELECT * FROM users")
        assert rows == [(1, "alice")]


# ---------------------------------------------------------------------------
# 9. close + reopen preserves state
# ---------------------------------------------------------------------------


def test_close_then_reopen_preserves_state(tmp_path):
    path = tmp_path / "persist.db"
    with tinydb.open(path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")

    # Reopen
    with tinydb.open(path) as db:
        rows = db.execute("SELECT * FROM users")
        assert rows == [(1, "alice")]


# ---------------------------------------------------------------------------
# 10. Invalid SQL -> ParseError
# ---------------------------------------------------------------------------


def test_invalid_sql_raises_parse_error(tmp_path):
    with _mk_db(tmp_path) as db:
        with pytest.raises(ParseError):
            db.execute("this is not sql at all")


def test_parse_error_is_tinydb_error():
    """ParseError must be a subclass of TinydbError (consistent surface)."""
    assert issubclass(ParseError, TinydbError)


# ---------------------------------------------------------------------------
# 11. tinydb.open returns Database
# ---------------------------------------------------------------------------


def test_open_returns_database(tmp_path):
    db = tinydb.open(tmp_path / "rtn.db")
    try:
        assert isinstance(db, Database)
    finally:
        db.close()


def test_database_and_open_in_public_surface():
    """Both Database and open must be importable from tinydb itself."""
    assert hasattr(tinydb, "Database")
    assert hasattr(tinydb, "open")
    assert tinydb.Database is Database
    assert tinydb.open is tinydb_open
