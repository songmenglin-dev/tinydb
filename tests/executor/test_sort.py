"""T-5.4 executor tests — Sort + Limit (in-memory).

Each test arranges a small ``users``-family table in a fresh
:class:`Catalog`, inserts rows via :class:`Heap`, plans a SELECT, runs
it through :class:`Executor`, and asserts the resulting list of rows.

T-5.4 narrows the previous ``Limit = Sort`` alias into two separate
plan dataclasses.  The planner emits ``Sort`` for ``ORDER BY`` and a
distinct :class:`Limit` plan for ``LIMIT/OFFSET`` after any Sort.
"""

from __future__ import annotations

import pytest

from tinydb.executor.planner import (
    Executor,
    UnknownColumnError,
    plan,
)
from tinydb.executor.ops import Limit, Sort
from tinydb.sql.parser import parse_dml_string as parse
from tinydb.storage.heap import Heap
from tinydb.types.codec import encode_row
from tinydb.types.system import Column, TypeTag


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _tags(meta):
    return tuple(c.tag for c in meta.columns)


def _seed_users(catalog):
    """Insert the canonical T-5.4 sample data and return ``(meta, heap)``."""
    meta = catalog.get_table("users")
    heap = Heap(catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
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


def _seed_nullable(catalog):
    """Insert a ``salary`` column where some rows are NULL.

    Returns ``(meta, heap)``.  Schema: ``id INT PK, name TEXT, age INT,
    salary JSON`` (JSON is the only column type that accepts None
    alongside other values — see codec._check_int_range / Null-tag).
    """
    meta = catalog.get_table("salaries")
    heap = Heap(catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    rows = [
        (1, "alice", 30, 100),
        (2, "bob", 25, None),
        (3, "carol", 40, 200),
        (4, "dave", 19, None),
        (5, "eve", 50, 150),
    ]
    for r in rows:
        heap.insert(encode_row(r, _tags(meta)))
    return meta, heap


def _run(catalog, sql: str):
    stmt = parse(sql)
    p = plan(stmt, catalog)
    return Executor(catalog, pager=catalog._pager).execute(p)


def _by_id(rows):
    """Return rows keyed by first column (id) for stable comparison."""
    return {r[0]: r for r in rows}


@pytest.fixture
def nullable_catalog(catalog):
    """Catalog with a ``salaries`` table that has a NULL-allowed column.

    Uses :class:`TypeTag.Json` for the nullable ``salary`` column
    because the v0.1 codec only permits ``None`` on a Null or Json
    type tag (see ``tinydb.types.codec``).
    """
    catalog.create_table(
        "salaries",
        [
            Column(name="id", tag=TypeTag.Int, primary_key=True),
            Column(name="name", tag=TypeTag.Text),
            Column(name="age", tag=TypeTag.Int),
            Column(name="salary", tag=TypeTag.Json),
        ],
    )
    return catalog


# ---------------------------------------------------------------------------
# 1. ORDER BY age ASC (single int column)
# ---------------------------------------------------------------------------


def test_sort_ascending_single_int(users_catalog):
    """ORDER BY age sorts rows into ascending age order."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users ORDER BY age")
    # ages: alice=30, bob=25, carol=40, dave=19, eve=50
    assert result == [
        (4, "dave", 19),
        (2, "bob", 25),
        (1, "alice", 30),
        (3, "carol", 40),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 2. ORDER BY age DESC
# ---------------------------------------------------------------------------


def test_sort_descending_single_int(users_catalog):
    """ORDER BY age DESC reverses the ASC ordering."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users ORDER BY age DESC")
    assert result == [
        (5, "eve", 50),
        (3, "carol", 40),
        (1, "alice", 30),
        (2, "bob", 25),
        (4, "dave", 19),
    ]


# ---------------------------------------------------------------------------
# 3. ORDER BY two columns with tie-breaker (e.g. by dept ASC, age DESC)
# ---------------------------------------------------------------------------


def test_sort_multi_key_tie_breaker(users_catalog):
    """Multi-key sort uses second key as tie-breaker.

    For this case we ORDER BY age ASC, id DESC: ages 25/30/40/50 are
    distinct so id DESC dominates.  Confirm the planner + executor
    honour the second key when the first would tie.

    More directly: order by ``(age // 10) ASC, age DESC`` -- the floor
    of age creates ties that the second key must break.  But we don't
    support expressions in ORDER BY.  Use age//1 as the trivial case
    (always ties): tie-breaker is the second key.
    """
    # Easier: introduce two rows with the same age to exercise tie-break.
    # Insert an extra row by direct heap insert.
    meta, _ = _seed_users(users_catalog)
    heap = Heap(users_catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    heap.insert(encode_row((6, "frank", 30), _tags(meta)))  # tie with alice
    result = _run(
        users_catalog,
        "SELECT * FROM users ORDER BY age ASC, id DESC",
    )
    # Two rows tied at age=30: alice (id=1) and frank (id=6); tie-breaker id DESC
    # gives frank before alice.  Other ages are unique so order is:
    # dave(19), bob(25), frank(30), alice(30), carol(40), eve(50)
    assert result == [
        (4, "dave", 19),
        (2, "bob", 25),
        (6, "frank", 30),
        (1, "alice", 30),
        (3, "carol", 40),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 4. LIMIT 3 on 5 rows → first 3
# ---------------------------------------------------------------------------


def test_limit_three_on_five(users_catalog):
    """LIMIT 3 on 5 rows returns the first 3 in declared order."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users LIMIT 3")
    assert result == [
        (1, "alice", 30),
        (2, "bob", 25),
        (3, "carol", 40),
    ]


# ---------------------------------------------------------------------------
# 5. OFFSET 2 LIMIT 3 → middle 3
# ---------------------------------------------------------------------------


def test_offset_and_limit(users_catalog):
    """LIMIT 3 OFFSET 2 returns rows [2..5) (3-row window after 2 skip)."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users LIMIT 3 OFFSET 2")
    assert result == [
        (3, "carol", 40),
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 6. LIMIT 100 on 5 rows → all 5 (limit > rowcount)
# ---------------------------------------------------------------------------


def test_limit_greater_than_rowcount(users_catalog):
    """LIMIT 100 on 5 rows returns all 5 (no error, no padding)."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users LIMIT 100")
    assert result == [
        (1, "alice", 30),
        (2, "bob", 25),
        (3, "carol", 40),
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 7. ORDER BY + LIMIT combined
# ---------------------------------------------------------------------------


def test_sort_then_limit(users_catalog):
    """ORDER BY age DESC LIMIT 3 returns the 3 oldest users in age order."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog,
        "SELECT * FROM users ORDER BY age DESC LIMIT 3",
    )
    assert result == [
        (5, "eve", 50),
        (3, "carol", 40),
        (1, "alice", 30),
    ]


# ---------------------------------------------------------------------------
# 8. ORDER BY string column (text)
# ---------------------------------------------------------------------------


def test_sort_by_text(users_catalog):
    """ORDER BY name sorts alphabetically."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT * FROM users ORDER BY name")
    # alphabetical: alice, bob, carol, dave, eve
    assert result == [
        (1, "alice", 30),
        (2, "bob", 25),
        (3, "carol", 40),
        (4, "dave", 19),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 9. ORDER BY nullable column — NULLs sort last in ASC
# ---------------------------------------------------------------------------


def test_sort_nulls_last_in_asc(nullable_catalog):
    """NULL values sort last in ASC; first in DESC (SQLite default)."""
    _seed_nullable(nullable_catalog)
    result = _run(
        nullable_catalog, "SELECT * FROM salaries ORDER BY salary"
    )
    # Non-null salaries ascending: 100, 150, 200; then NULLs (bob, dave).
    by_id = _by_id(result)
    # The three non-nulls come first in order, then bob + dave (any order).
    assert result[0] == (1, "alice", 30, 100)
    assert result[1] == (5, "eve", 50, 150)
    assert result[2] == (3, "carol", 40, 200)
    assert by_id[2] == (2, "bob", 25, None)
    assert by_id[4] == (4, "dave", 19, None)


def test_sort_nulls_first_in_desc(nullable_catalog):
    """NULL values sort first in DESC (SQLite default)."""
    _seed_nullable(nullable_catalog)
    result = _run(
        nullable_catalog, "SELECT * FROM salaries ORDER BY salary DESC"
    )
    # NULLs first (bob, dave), then 200, 150, 100.
    by_id = _by_id(result)
    assert by_id[2] == (2, "bob", 25, None)
    assert by_id[4] == (4, "dave", 19, None)
    assert result[2] == (3, "carol", 40, 200)
    assert result[3] == (5, "eve", 50, 150)
    assert result[4] == (1, "alice", 30, 100)


# ---------------------------------------------------------------------------
# 10. Unknown ORDER BY column → UnknownColumnError
# ---------------------------------------------------------------------------


def test_sort_unknown_column_raises(users_catalog):
    """An ORDER BY column that does not exist raises UnknownColumnError."""
    _seed_users(users_catalog)
    with pytest.raises(UnknownColumnError):
        _run(users_catalog, "SELECT * FROM users ORDER BY color")


# ---------------------------------------------------------------------------
# 11. Multiple ORDER BY columns with tied values → tie-breaker works
# ---------------------------------------------------------------------------


def test_sort_multi_key_uses_tie_breaker_for_ties(users_catalog):
    """When the first key ties, the second key breaks the tie."""
    meta, _ = _seed_users(users_catalog)
    heap = Heap(users_catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    # Two rows with age=25, ids 2 and 7.
    heap.insert(encode_row((7, "gina", 25), _tags(meta)))
    # Two rows with age=30, ids 1 and 6 (carried from test 3 stays if set;
    # but this test is independent — we seeded _seed_users fresh above).
    heap.insert(encode_row((6, "frank", 30), _tags(meta)))
    # ORDER BY age ASC, id ASC -- both keys matter
    result = _run(
        users_catalog,
        "SELECT * FROM users ORDER BY age ASC, id ASC",
    )
    # ages: 19 (dave id=4), 25 (bob id=2, gina id=7), 30 (alice id=1, frank id=6),
    # 40 (carol id=3), 50 (eve id=5)
    assert result == [
        (4, "dave", 19),
        (2, "bob", 25),
        (7, "gina", 25),
        (1, "alice", 30),
        (6, "frank", 30),
        (3, "carol", 40),
        (5, "eve", 50),
    ]


# ---------------------------------------------------------------------------
# 12. Sort with empty result → no crash, returns []
# ---------------------------------------------------------------------------


def test_sort_on_empty_table(users_catalog):
    """Sorting an empty table returns [] without error."""
    result = _run(users_catalog, "SELECT * FROM users ORDER BY age")
    assert result == []


def test_limit_on_empty_table(users_catalog):
    """Limiting an empty table returns [] without error."""
    result = _run(users_catalog, "SELECT * FROM users LIMIT 5")
    assert result == []


# ---------------------------------------------------------------------------
# Plan-shape sanity checks — Limit is its own dataclass (T-5.4 split)
# ---------------------------------------------------------------------------


def test_limit_plan_is_distinct_from_sort(users_catalog):
    """After T-5.4, Limit is its own dataclass — not a Sort alias."""
    assert Limit is not Sort


def test_limit_plan_shape_for_limit_only(users_catalog):
    """LIMIT alone (no ORDER BY) emits a Limit wrapping Project, no Sort."""
    from tinydb.executor.ops import Project

    stmt = parse("SELECT * FROM users LIMIT 3")
    p = plan(stmt, users_catalog)

    assert isinstance(p, Limit)
    assert p.limit == 3
    assert p.offset == 0
    # Plan.tree shape: Limit(Project(SeqScan)) — no Sort wrapper.
    proj = p.src
    assert isinstance(proj, Project)
    assert not isinstance(proj, Sort)


def test_limit_plan_shape_for_limit_and_offset(users_catalog):
    """OFFSET is captured on the Limit plan."""
    stmt = parse("SELECT * FROM users LIMIT 3 OFFSET 2")
    p = plan(stmt, users_catalog)

    assert isinstance(p, Limit)
    assert p.limit == 3
    assert p.offset == 2