"""T-6.4 — Constraint enforcement inside ``TransactionManager``.

Integration tests stand up a fresh Pager / Catalog / IndexManager /
TransactionManager and run a real DML sequence through
``mgr.transaction()``.  REQ-TRX-3: a UNIQUE / NOT NULL violation
inside a transaction must roll the WHOLE transaction back; the table
state after the failed tx must match the state before the tx started.

Known scope fence
-----------------
Single-statement tx rollback works because :class:`Insert` /
:class:`Update` probe UNIQUE indexes BEFORE writing to the heap, so
a rejected row leaves the in-memory heap clean.  Multi-statement tx
rollback is NOT yet durable — there is no heap UNDO log on disk;
T-6.6 wires that.  Test #10 pins the limitation so future readers
see exactly which cases will tighten once the undo log lands.
"""
from __future__ import annotations

from typing import Tuple

import pytest

from tinydb.errors import ConstraintViolation, NotNullViolation, TinydbError
from tinydb.executor.executor import Executor
from tinydb.executor.planner import plan
from tinydb.index.manager import IndexManager
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.catalog import Catalog
from tinydb.storage.pager import Pager
from tinydb.tx import RT_BEGIN, RT_COMMIT, RT_ROLLBACK, WAL, TransactionManager
from tinydb.types.system import Column, TypeTag


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


@pytest.fixture
def users_db(tmp_path) -> Tuple[
    Pager, Catalog, IndexManager, TransactionManager, WAL, Executor
]:
    """Pager + Catalog (users PK/UNIQUE/NN) + IndexManager + mgr + executor.

    Schema: users(id INT PK/UNIQUE/NOT NULL, name TEXT NOT NULL, age INT).
    Index: idx_users_id UNIQUE on (id).
    """
    pager = Pager.open(tmp_path / "test.db")
    catalog = Catalog(pager)
    catalog.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True, unique=True, not_null=True),
            _col("name", TypeTag.Text, not_null=True),
            _col("age", TypeTag.Int),
        ],
    )
    wal_path = tmp_path / "test.wal"
    wal = WAL(wal_path, mode="w+b")
    wal.close()
    wal = WAL(wal_path)
    indexer = IndexManager(catalog, pager)
    indexer.create_index("idx_users_id", "users", ("id",), unique=True)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer)
    try:
        yield pager, catalog, indexer, mgr, wal, executor
    finally:
        wal.close()
        pager.close()


def _run_dml(executor: Executor, catalog: Catalog, sql: str):
    return executor.execute(plan(parse(sql), catalog, indexer=executor.indexer))


def _select_users(executor: Executor, catalog: Catalog):
    return sorted(_run_dml(executor, catalog, "SELECT * FROM users"))


def _wal_types(wal: WAL):
    return [r.type for r in wal.iter_from(1)]


# 1. UNIQUE violation → whole tx rolls back.
def test_unique_violation_rolls_back_transaction(users_db):
    _, catalog, _, mgr, wal, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with pytest.raises(ConstraintViolation):
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'bob', 40)")
    assert _select_users(executor, catalog) == [(1, "alice", 30)]
    assert _wal_types(wal) == [RT_BEGIN, RT_COMMIT, RT_BEGIN, RT_ROLLBACK]


# 2. NOT NULL violation → table state unchanged.
def test_not_null_violation_rolls_back_transaction(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with pytest.raises(NotNullViolation):
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (2, NULL, 25)")
    assert _select_users(executor, catalog) == [(1, "alice", 30)]


# 3. Multi-row INSERT with one violation → whole batch rolls back.
def test_multi_row_insert_with_violation_rolls_back_all_rows(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with pytest.raises(ConstraintViolation):
        with mgr.transaction():
            _run_dml(
                executor, catalog,
                "INSERT INTO users VALUES "
                "(2, 'bob', 25), (3, 'carol', 22), (1, 'clash', 99)",
            )
    assert _select_users(executor, catalog) == [(1, "alice", 30)]


# 4. After a failed tx, a follow-up tx with valid DML succeeds.
def test_followup_transaction_after_failure_succeeds(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with pytest.raises(ConstraintViolation):
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'bob', 40)")
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'bob', 40)")
    assert _select_users(executor, catalog) == [(1, "alice", 30), (2, "bob", 40)]


# 5. Empty tx (BEGIN/COMMIT) leaves the table untouched.
def test_empty_transaction_leaves_table_unchanged(users_db):
    _, catalog, _, mgr, wal, executor = users_db
    with mgr.transaction():
        pass
    assert _select_users(executor, catalog) == []
    assert _wal_types(wal) == [RT_BEGIN, RT_COMMIT]


# 6. UPDATE whose predicate matches nothing commits cleanly (no-op).
def test_update_no_match_is_a_safe_noop(users_db):
    _, catalog, _, mgr, wal, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with mgr.transaction():
        _run_dml(executor, catalog, "UPDATE users SET name = 'x' WHERE id = 999")
    assert _select_users(executor, catalog) == [(1, "alice", 30)]
    assert _wal_types(wal) == [RT_BEGIN, RT_COMMIT, RT_BEGIN, RT_COMMIT]


# 7. UPDATE that violates UNIQUE rolls back the tx.
def test_update_unique_violation_rolls_back(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'bob', 25)")
    with pytest.raises(ConstraintViolation):
        with mgr.transaction():
            _run_dml(executor, catalog, "UPDATE users SET id = 2 WHERE id = 1")
    assert _select_users(executor, catalog) == [(1, "alice", 30), (2, "bob", 25)]


# 8. Multiple UNIQUE indexes — any violation triggers rollback.
def test_multiple_unique_indexes_any_violation_rolls_back(tmp_path):
    pager = Pager.open(tmp_path / "test.db")
    catalog = Catalog(pager)
    catalog.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True, not_null=True),
            _col("email", TypeTag.Text, not_null=True),
            _col("age", TypeTag.Int),
        ],
    )
    wal_path = tmp_path / "test.wal"
    wal = WAL(wal_path, mode="w+b")
    wal.close()
    wal = WAL(wal_path)
    indexer = IndexManager(catalog, pager)
    indexer.create_index("idx_users_id", "users", ("id",), unique=True)
    indexer.create_index("idx_users_email", "users", ("email",), unique=True)
    mgr = TransactionManager(pager, wal)
    executor = Executor(catalog, pager=pager, indexer=indexer)
    try:
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'a@x', 30)")
        with pytest.raises(ConstraintViolation):
            with mgr.transaction():
                _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'b@x', 25)")
        with pytest.raises(ConstraintViolation):
            with mgr.transaction():
                _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'a@x', 25)")
        assert sorted(_run_dml(executor, catalog, "SELECT * FROM users")) == [
            (1, "a@x", 30)
        ]
    finally:
        wal.close()
        pager.close()


# 9. ConstraintViolation is a TinydbError subclass.
def test_constraint_violation_is_a_tinydb_error(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with pytest.raises(TinydbError) as exc_info:
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'bob', 40)")
    assert isinstance(exc_info.value, ConstraintViolation)


# 10. Known limitation (T-6.6): multi-statement tx with mid-tx rollback.
def test_multi_statement_tx_known_limitation_until_t66(users_db):
    _, catalog, _, mgr, _, executor = users_db
    with mgr.transaction():
        _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'alice', 30)")
    with pytest.raises(ConstraintViolation):
        with mgr.transaction():
            _run_dml(executor, catalog, "INSERT INTO users VALUES (2, 'bob', 25)")
            _run_dml(executor, catalog, "INSERT INTO users VALUES (1, 'clash', 99)")
    # Pin the current behaviour — the row landed in the in-memory heap
    # because there is no UNDO log yet.  T-6.6 will tighten this to
    # `== [(1, 'alice', 30)]`.
    assert _select_users(executor, catalog) == [(1, "alice", 30), (2, "bob", 25)]