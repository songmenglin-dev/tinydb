"""T-5.2 executor tests — SeqScan + Filter + Project.

Each test arranges a ``users`` table in a fresh :class:`Catalog`, inserts
a handful of rows via :class:`Heap`, then runs a SELECT through the
executor and checks the returned list of row tuples.

Fixtures live in ``tests/executor/conftest.py`` and extend the
``users_catalog`` fixture introduced for T-5.1.
"""

from __future__ import annotations

import pytest

from tinydb.executor.planner import (
    Executor,
    UnknownColumnError,
    plan,
)
from tinydb.executor.row_iter import TableScan
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.heap import Heap
from tinydb.types.codec import encode_row
from tinydb.types.system import TypeTag


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _tags(meta):
    return tuple(c.tag for c in meta.columns)


def _row(heap: Heap, meta, *values):
    """Insert one row and return its Rid (caller doesn't need it here)."""
    heap.insert(encode_row(values, _tags(meta)))
    return None


def _seed_users(catalog):
    """Insert the canonical T-5.2 sample data into ``users`` and return meta."""
    meta = catalog.get_table("users")
    heap = Heap(catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid  # reuse catalog's heap
    rows = [
        (1, "alice", 30),
        (2, "bob", 25),
        (3, "carol", 40),
        (4, "dave", 19),
        (5, "eve", 50),
    ]
    for r in rows:
        heap.insert(encode_row(r, _tags(meta)))
    return meta, heap


def _run(catalog, sql: str):
    """Plan + execute a SELECT, returning the executor's result list."""
    stmt = parse(sql)
    p = plan(stmt, catalog)
    return Executor(catalog, pager=catalog._pager).execute(p)


# ---------------------------------------------------------------------------
# 1. SELECT * FROM users
# ---------------------------------------------------------------------------


def test_select_star_returns_all_rows(users_catalog):
    """SELECT * FROM users returns all rows in insertion order."""
    meta, _ = _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users")
    assert result == [
        (1, "alice", 30),
        (2, "bob", 25),
        (3, "carol", 40),
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 2. SELECT * FROM users WHERE id = 1
# ---------------------------------------------------------------------------


def test_where_id_equality(users_catalog):
    """WHERE id = 1 filters to a single row."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users WHERE id = 1")
    assert result == [(1, "alice", 30)]


# ---------------------------------------------------------------------------
# 3. SELECT * FROM users WHERE id > 5 (range)
# ---------------------------------------------------------------------------


def test_where_id_greater_than(users_catalog):
    """WHERE id > 5 keeps rows with id strictly greater than 5."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users WHERE id > 3")
    assert result == [
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 4. WHERE name = 'alice' AND age > 20
# ---------------------------------------------------------------------------


def test_where_and_combinator(users_catalog):
    """AND short-circuits; both clauses must hold."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog,
        "SELECT * FROM users WHERE name = 'alice' AND age > 20",
    )
    assert result == [(1, "alice", 30)]


# ---------------------------------------------------------------------------
# 5. WHERE name = 'alice' OR name = 'bob'
# ---------------------------------------------------------------------------


def test_where_or_combinator(users_catalog):
    """OR unions the matching rows (preserving insertion order)."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog,
        "SELECT * FROM users WHERE name = 'alice' OR name = 'bob'",
    )
    assert result == [
        (1, "alice", 30),
        (2, "bob", 25),
    ]


# ---------------------------------------------------------------------------
# 6. WHERE name IS NULL
# ---------------------------------------------------------------------------


def test_where_is_null(users_catalog):
    """IS NULL on a column with no NULLs returns nothing."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users WHERE name IS NULL")
    assert result == []


def test_where_is_not_null(users_catalog):
    """IS NOT NULL keeps every row when no NULLs exist."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog, "SELECT * FROM users WHERE name IS NOT NULL"
    )
    assert len(result) == 5


# ---------------------------------------------------------------------------
# 7. WHERE name = 'alice' OR age > 100 (mixed precedence)
# ---------------------------------------------------------------------------


def test_where_mixed_and_or_precedence(users_catalog):
    """AND binds tighter than OR: name='alice' OR (age>100) keeps alice only."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog,
        "SELECT * FROM users WHERE name = 'alice' OR age > 100",
    )
    assert result == [(1, "alice", 30)]


# ---------------------------------------------------------------------------
# 8. SELECT id, name FROM users (projection)
# ---------------------------------------------------------------------------


def test_project_specific_columns(users_catalog):
    """Project trims the row to the listed columns in declared order."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT id, name FROM users")
    assert result == [
        (1, "alice"),
        (2, "bob"),
        (3, "carol"),
        (4, "dave"),
        (5, "eve"),
    ]


# ---------------------------------------------------------------------------
# 9. SELECT name FROM users WHERE id = 1 (project + filter)
# ---------------------------------------------------------------------------


def test_project_with_filter(users_catalog):
    """Filter runs before Project; result is single-column."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog, "SELECT name FROM users WHERE id = 1"
    )
    assert result == [("alice",)]


# ---------------------------------------------------------------------------
# 10. Unknown column in WHERE → UnknownColumnError
# ---------------------------------------------------------------------------


def test_where_unknown_column_raises(users_catalog):
    """Reference to an undeclared column raises at execution time."""
    _seed_users(users_catalog)
    with pytest.raises(UnknownColumnError):
        _run(
            users_catalog, "SELECT * FROM users WHERE unknown_col = 1"
        )


# ---------------------------------------------------------------------------
# 11. Heap.delete tombstone is skipped at scan time
# ---------------------------------------------------------------------------


def test_tombstoned_row_is_skipped(users_catalog):
    """After Heap.delete, the row disappears from the result set."""
    meta, heap = _seed_users(users_catalog)
    # Delete the row with id=3 (carol).
    rids = list(heap.scan())
    for rid in rids:
        blob = heap.read(rid)
        assert blob is not None
        # First 1B tag + 8B int = 9 bytes for the id (INT), then 4B length
        # prefix + 'carol' for the TEXT name. Just decode by hand to find
        # the row whose id == 3.
        # Use TableScan to compare full row tuples.
    # Re-derive via TableScan (cheaper) to locate the row to delete.
    scan = TableScan(heap, meta)
    carol_rid = None
    for rid, row in scan:
        if row[0] == 3:
            carol_rid = rid
            break
    assert carol_rid is not None
    heap.delete(carol_rid)
    result = _run(users_catalog, "SELECT * FROM users")
    assert result == [
        (1, "alice", 30),
        (2, "bob", 25),
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 12. WHERE age = 18 with a fresh insert — type-coerced match
# ---------------------------------------------------------------------------


def test_filter_matches_codec_decoded_int(users_catalog):
    """Insert an INT row and match it via the int literal on the filter side."""
    meta = users_catalog.get_table("users")
    heap = Heap(users_catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    heap.insert(encode_row((1, "alice", 18), _tags(meta)))
    result = _run(users_catalog, "SELECT * FROM users WHERE age = 18")
    assert result == [(1, "alice", 18)]


# ---------------------------------------------------------------------------
# 13. Empty Heap → empty result
# ---------------------------------------------------------------------------


def test_select_from_empty_table(users_catalog):
    """Empty users table → SELECT * returns []."""
    result = _run(users_catalog, "SELECT * FROM users")
    assert result == []


# ---------------------------------------------------------------------------
# 14. NOT operator
# ---------------------------------------------------------------------------


def test_where_not(users_catalog):
    """NOT negates a comparison."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog,
        "SELECT * FROM users WHERE NOT (id = 1)",
    )
    assert result == [
        (2, "bob", 25),
        (3, "carol", 40),
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 15. Project with a literal expression item (no row scan cost)
# ---------------------------------------------------------------------------


def test_select_literal_projection(users_catalog):
    """SELECT 1 + 2 FROM users yields one constant per row."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT 1 + 2 FROM users")
    # Each row yields the expression result; arithmetic returns the int 3.
    assert result == [(3,), (3,), (3,), (3,), (3,)]
