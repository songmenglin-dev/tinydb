"""T-5.5 — INSERT / UPDATE / DELETE execution + index maintenance.

Each test builds a fresh :class:`Pager` + :class:`Catalog` + optional
:class:`IndexManager`, then plans and executes a DML statement through
:class:`Executor`.  The assert side varies: row counts returned, on-disk
state via SELECT, or :class:`ConstraintViolation` /
:class:`NotNullViolation` for the constraint tests.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ConstraintViolation, NotNullViolation
from tinydb.executor.executor import Executor
from tinydb.executor.planner import UnknownTableError, plan
from tinydb.index.manager import IndexManager
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.catalog import Catalog
from tinydb.storage.heap import Heap
from tinydb.storage.pager import Pager
from tinydb.types.codec import encode_row
from tinydb.types.system import Column, TypeTag


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _col(name: str, tag: TypeTag, **kw) -> Column:
    return Column(name=name, tag=tag, **kw)


def _tags(meta):
    return tuple(c.tag for c in meta.columns)


def _build_users_catalog(pager: Pager) -> Catalog:
    """A fresh Catalog with `users(id INT PK/NOT NULL, name TEXT, age INT)`."""
    cat = Catalog(pager)
    cat.create_table(
        "users",
        [
            _col("id", TypeTag.Int, primary_key=True, not_null=True),
            _col("name", TypeTag.Text),
            _col("age", TypeTag.Int),
        ],
    )
    return cat


def _seed(heap: Heap, meta, *rows) -> None:
    """Insert raw rows through the heap (no index manager)."""
    for r in rows:
        heap.insert(encode_row(r, _tags(meta)))


def _build_executor(cat: Catalog, mgr: IndexManager | None = None) -> Executor:
    """Wire an Executor against the catalog + optional IndexManager."""
    return Executor(cat, pager=cat._pager, indexer=mgr)


def _run_dml(cat: Catalog, sql: str, mgr: IndexManager | None = None):
    """Plan + execute a DML statement; return the executor's result list."""
    stmt = parse(sql)
    p = plan(stmt, cat, indexer=mgr)
    executor = _build_executor(cat, mgr)
    return executor.execute(p)


def _select_all(cat: Catalog, table: str = "users"):
    """Run `SELECT * FROM <table>` and return the row tuples."""
    stmt = parse(f"SELECT * FROM {table}")
    p = plan(stmt, cat)
    return Executor(cat, pager=cat._pager).execute(p)


# ---------------------------------------------------------------------------
# 1. INSERT round-trip
# ---------------------------------------------------------------------------


def test_insert_then_select_roundtrip(tmp_path):
    """INSERT then SELECT returns the row with decoded values."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        assert _select_all(cat) == [(1, "alice", 30)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 2. INSERT with NULL into nullable column
# ---------------------------------------------------------------------------


def test_insert_null_in_nullable_column(tmp_path):
    """INSERT a NULL into the nullable `name` column; SELECT yields NULL back."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, NULL, 30)")
        assert _select_all(cat) == [(1, None, 30)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 3. INSERT with NULL into NOT NULL column raises
# ---------------------------------------------------------------------------


def test_insert_null_in_not_null_column_raises(tmp_path):
    """`INSERT INTO users VALUES (NULL, 'a', 1)` (id PK/NOT NULL) raises."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        # id has primary_key=True → not_null=True too.
        with pytest.raises(NotNullViolation):
            _run_dml(cat, "INSERT INTO users VALUES (NULL, 'alice', 30)")
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 4. INSERT into non-existent table → UnknownTableError
# ---------------------------------------------------------------------------


def test_insert_unknown_table_raises(tmp_path):
    """INSERT into a table that is not registered raises UnknownTableError."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        with pytest.raises(UnknownTableError):
            _run_dml(cat, "INSERT INTO ghost VALUES (1, 'a', 1)")
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 5. UPDATE with WHERE predicate
# ---------------------------------------------------------------------------


def test_update_with_where_clause(tmp_path):
    """`UPDATE users SET name='bob' WHERE id=1` updates only the matching row.

    Heap order may change because UPDATE is implemented as delete + insert
    (Heap has no in-place update).  Compare as a multiset.
    """
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        _run_dml(cat, "INSERT INTO users VALUES (2, 'carol', 40)")
        _run_dml(cat, "UPDATE users SET name = 'bob' WHERE id = 1")
        assert sorted(_select_all(cat)) == [
            (1, "bob", 30),
            (2, "carol", 40),
        ]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 6. UPDATE setting NOT NULL column to NULL raises
# ---------------------------------------------------------------------------


def test_update_set_not_null_to_null_raises(tmp_path):
    """`UPDATE users SET id=NULL WHERE id=1` raises NotNullViolation."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        with pytest.raises(NotNullViolation):
            _run_dml(cat, "UPDATE users SET id = NULL WHERE id = 1")
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 7. UPDATE with NOT (...) predicate
# ---------------------------------------------------------------------------


def test_update_with_not_predicate(tmp_path):
    """`UPDATE users SET age = 99 WHERE NOT (id = 1)` updates all but id=1."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        _run_dml(cat, "INSERT INTO users VALUES (2, 'bob', 25)")
        _run_dml(cat, "INSERT INTO users VALUES (3, 'carol', 40)")
        _run_dml(cat, "UPDATE users SET age = 99 WHERE NOT (id = 1)")
        assert sorted(_select_all(cat)) == [
            (1, "alice", 30),
            (2, "bob", 99),
            (3, "carol", 99),
        ]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 8. UPDATE without predicate → all rows
# ---------------------------------------------------------------------------


def test_update_without_predicate_affects_all(tmp_path):
    """`UPDATE users SET age = 0` (no WHERE) sets every row's age to 0."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        _run_dml(cat, "INSERT INTO users VALUES (2, 'bob', 25)")
        _run_dml(cat, "UPDATE users SET age = 0")
        assert _select_all(cat) == [
            (1, "alice", 0),
            (2, "bob", 0),
        ]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 9. DELETE with WHERE predicate
# ---------------------------------------------------------------------------


def test_delete_with_where_clause(tmp_path):
    """`DELETE FROM users WHERE id = 1` removes only the matching row."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        _run_dml(cat, "INSERT INTO users VALUES (2, 'bob', 25)")
        _run_dml(cat, "DELETE FROM users WHERE id = 1")
        assert _select_all(cat) == [(2, "bob", 25)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 10. DELETE without predicate → table empty
# ---------------------------------------------------------------------------


def test_delete_without_predicate_empties_table(tmp_path):
    """`DELETE FROM users` (no WHERE) removes every row."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        _run_dml(cat, "INSERT INTO users VALUES (2, 'bob', 25)")
        _run_dml(cat, "DELETE FROM users")
        assert _select_all(cat) == []
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 11. UNIQUE constraint violation on INSERT
# ---------------------------------------------------------------------------


def test_unique_index_insert_duplicate_raises(tmp_path):
    """CREATE UNIQUE INDEX then INSERT duplicate raises ConstraintViolation."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_id_unique", "users", ("id",), unique=True)
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)", mgr=mgr)
        with pytest.raises(ConstraintViolation):
            _run_dml(
                cat, "INSERT INTO users VALUES (1, 'bob', 99)", mgr=mgr
            )
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 12. End-to-end index maintenance: INSERT/UPDATE/DELETE keep index in sync
# ---------------------------------------------------------------------------


def test_index_maintenance_end_to_end(tmp_path):
    """Build an index on `users(name)`, INSERT 3, UPDATE 1, DELETE 1.

    After each operation a `WHERE name = ...` lookup (via IndexScan) must
    return the expected row(s).  This proves the index never holds
    orphans or missing entries.
    """
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        mgr = IndexManager(cat, pager)
        mgr.create_index("idx_users_name", "users", ("name",), unique=False)

        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)", mgr=mgr)
        _run_dml(cat, "INSERT INTO users VALUES (2, 'bob', 25)", mgr=mgr)
        _run_dml(cat, "INSERT INTO users VALUES (3, 'carol', 40)", mgr=mgr)

        # After INSERTs: alice/bob/carol each resolve via the index.
        def _by_name(target: str):
            stmt = parse(f"SELECT * FROM users WHERE name = '{target}'")
            p = plan(stmt, cat, indexer=mgr)
            return Executor(cat, pager=cat._pager, indexer=mgr).execute(p)

        assert _by_name("alice") == [(1, "alice", 30)]
        assert _by_name("bob") == [(2, "bob", 25)]
        assert _by_name("carol") == [(3, "carol", 40)]

        # UPDATE bob → 'bobby'.  Old key must be gone, new key present.
        _run_dml(cat, "UPDATE users SET name = 'bobby' WHERE id = 2", mgr=mgr)
        assert _by_name("bob") == []  # old key removed
        assert _by_name("bobby") == [(2, "bobby", 25)]

        # DELETE alice.  Index no longer surfaces her row.
        _run_dml(cat, "DELETE FROM users WHERE id = 1", mgr=mgr)
        assert _by_name("alice") == []
        # Surviving row still indexable.
        assert _by_name("carol") == [(3, "carol", 40)]
    finally:
        pager.close()


# ---------------------------------------------------------------------------
# 13. Row count returns for INSERT and DELETE
# ---------------------------------------------------------------------------


def test_insert_and_delete_return_row_counts(tmp_path):
    """INSERT yields (1,); DELETE yields (N,) where N is the affected count."""
    pager = Pager.open(tmp_path / "test.db")
    try:
        cat = _build_users_catalog(pager)
        # INSERT one row → (1,)
        result = _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        assert result == [(1,)]

        # DELETE without predicate → (N,) where N == row count (1).
        result = _run_dml(cat, "DELETE FROM users")
        assert result == [(1,)]

        # Re-seed two rows, DELETE with WHERE id=1 → (1,).
        _run_dml(cat, "INSERT INTO users VALUES (1, 'alice', 30)")
        _run_dml(cat, "INSERT INTO users VALUES (2, 'bob', 25)")
        result = _run_dml(cat, "DELETE FROM users WHERE id = 1")
        assert result == [(1,)]
    finally:
        pager.close()
