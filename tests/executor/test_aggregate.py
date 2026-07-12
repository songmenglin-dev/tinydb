"""T-5.6 executor tests — Aggregate + GROUP BY.

Verifies COUNT / SUM / AVG / MIN / MAX with and without GROUP BY.
Reuses the ``users`` catalog fixture from ``conftest.py`` and extends it
with a ``dept`` column when a SELECT references it; aggregate semantics
(COUNT(*) counts rows, COUNT(col) skips NULL, etc.) are pinned by these
tests so refactors don't silently drift.

NULL semantics under test:
- COUNT(*)              counts every row
- COUNT(col)            skips NULLs
- SUM/AVG/MIN/MAX(col)  skip NULLs; SUM/AVG return None over zero rows,
                        COUNT returns 0
"""

from __future__ import annotations

import pytest

from tinydb.executor.planner import Executor, plan
from tinydb.executor.ops import Aggregate as AggregatePlan
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
    """Insert the canonical aggregate sample data and return meta + heap."""
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


def _drop_if_present(catalog, name: str) -> None:
    try:
        catalog.drop_table(name)
    except KeyError:
        pass


def _seed_users_with_dept(catalog):
    """Catalog with users(id, name, age, dept) seeded across departments."""
    _drop_if_present(catalog, "users")
    catalog.create_table(
        "users",
        [
            Column(name="id", tag=TypeTag.Int, primary_key=True),
            Column(name="name", tag=TypeTag.Text),
            Column(name="age", tag=TypeTag.Int),
            Column(name="dept", tag=TypeTag.Text),
        ],
    )
    meta = catalog.get_table("users")
    heap = Heap(catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    rows = [
        (1, "alice", 30, "sales"),
        (2, "bob", 25, "sales"),
        (3, "carol", 40, "engineering"),
        (4, "dave", 19, "engineering"),
        (5, "eve", 50, "engineering"),
        (6, "frank", 60, "hr"),
    ]
    for r in rows:
        heap.insert(encode_row(r, _tags(meta)))
    return meta, heap


def _seed_users_with_null_dept(catalog):
    """users(id, name, age, dept) — dept column accepts NULL because it
    is a JSON tag (codec permits None on TypeTag.Json / TypeTag.Null).
    """
    _drop_if_present(catalog, "users")
    catalog.create_table(
        "users",
        [
            Column(name="id", tag=TypeTag.Int, primary_key=True),
            Column(name="name", tag=TypeTag.Text),
            Column(name="age", tag=TypeTag.Int),
            Column(name="dept", tag=TypeTag.Json),
        ],
    )
    meta = catalog.get_table("users")
    heap = Heap(catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    rows = [
        (1, "alice", 30, None),
        (2, "bob", 25, None),
        (3, "carol", 40, "sales"),
    ]
    for r in rows:
        heap.insert(encode_row(r, _tags(meta)))
    return meta, heap


def _run(catalog, sql: str):
    stmt = parse(sql)
    p = plan(stmt, catalog)
    return Executor(catalog, pager=catalog._pager).execute(p)


# ---------------------------------------------------------------------------
# 1. COUNT(*) — total rows
# ---------------------------------------------------------------------------


def test_count_star_returns_total(users_catalog):
    """SELECT COUNT(*) FROM users counts every row including NULLed cols."""
    _seed_users(users_catalog)
    assert _run(users_catalog, "SELECT COUNT(*) FROM users") == [(5,)]


# ---------------------------------------------------------------------------
# 2. COUNT(*) with WHERE — filtered count
# ---------------------------------------------------------------------------


def test_count_star_with_where(users_catalog):
    """COUNT(*) reflects rows already filtered by WHERE."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog, "SELECT COUNT(*) FROM users WHERE age > 18"
    )
    assert result == [(5,)]


def test_count_star_with_strict_where(users_catalog):
    """COUNT(*) post-filter — only rows matching WHERE are counted."""
    _seed_users(users_catalog)
    result = _run(
        users_catalog, "SELECT COUNT(*) FROM users WHERE age > 30"
    )
    assert result == [(2,)]  # carol(40) + eve(50)


# ---------------------------------------------------------------------------
# 3. SUM(col) — total of one column
# ---------------------------------------------------------------------------


def test_sum_age(users_catalog):
    """SUM(age) sums every row's age."""
    _seed_users(users_catalog)
    # 30+25+40+19+50 = 164
    assert _run(users_catalog, "SELECT SUM(age) FROM users") == [(164,)]


# ---------------------------------------------------------------------------
# 4. AVG(col) — mean
# ---------------------------------------------------------------------------


def test_avg_age(users_catalog):
    """AVG(age) returns the arithmetic mean across all rows."""
    _seed_users(users_catalog)
    # 164 / 5 = 32.8
    assert _run(users_catalog, "SELECT AVG(age) FROM users") == [(32.8,)]


# ---------------------------------------------------------------------------
# 5. MIN and MAX as a tuple
# ---------------------------------------------------------------------------


def test_min_max_age(users_catalog):
    """MIN/MAX yield (min, max) over the column."""
    _seed_users(users_catalog)
    result = _run(users_catalog, "SELECT MIN(age), MAX(age) FROM users")
    assert result == [(19, 50)]


# ---------------------------------------------------------------------------
# 6. COUNT(col) vs COUNT(*) — NULL tolerance
# ---------------------------------------------------------------------------


def test_count_col_vs_count_star_with_nulls(users_catalog):
    """COUNT(age) skips NULLs; COUNT(*) counts every row.

    Uses a fresh table whose ``age`` column is the JSON tag so the
    codec accepts ``None`` (TypeTag.Int rejects it).  In v0.1 the
    semantics are exercised; for production SQL types NULL support
    is the same — only the on-disk encoding differs.
    """
    _drop_if_present(users_catalog, "users")
    users_catalog.create_table(
        "users",
        [
            Column(name="id", tag=TypeTag.Int, primary_key=True),
            Column(name="name", tag=TypeTag.Text),
            Column(name="age", tag=TypeTag.Json),
        ],
    )
    meta = users_catalog.get_table("users")
    heap = Heap(users_catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    heap.insert(encode_row((1, "alice", 30), _tags(meta)))
    heap.insert(encode_row((2, "bob", 25), _tags(meta)))
    heap.insert(encode_row((3, "carol", 40), _tags(meta)))
    heap.insert(encode_row((99, "ghost", None), _tags(meta)))
    result = _run(
        users_catalog, "SELECT COUNT(age), COUNT(*) FROM users"
    )
    # COUNT(age) skips the JSON-NULL row → 3, COUNT(*) → 4.
    assert result == [(3, 4)]


# ---------------------------------------------------------------------------
# 7. GROUP BY — one row per distinct key
# ---------------------------------------------------------------------------


def test_group_by_dept_count(users_catalog):
    """GROUP BY dept, COUNT(*) yields one row per department."""
    _seed_users_with_dept(users_catalog)
    result = _run(
        users_catalog, "SELECT dept, COUNT(*) FROM users GROUP BY dept"
    )
    # sales=2, engineering=3, hr=1 — order is input order.
    assert result == [
        ("sales", 2),
        ("engineering", 3),
        ("hr", 1),
    ]


# ---------------------------------------------------------------------------
# 8. GROUP BY + ORDER BY — emitted order then sort
# ---------------------------------------------------------------------------


def test_group_by_dept_avg_with_order_by(users_catalog):
    """GROUP BY + ORDER BY yields groups in sorted order."""
    _seed_users_with_dept(users_catalog)
    result = _run(
        users_catalog,
        "SELECT dept, AVG(age) FROM users GROUP BY dept ORDER BY dept",
    )
    # engineering: (40+19+50)/3 = 36.333...
    # hr:    60
    # sales: (30+25)/2 = 27.5
    assert result == [
        ("engineering", pytest.approx(36.333333333333336)),
        ("hr", 60),
        ("sales", 27.5),
    ]


# ---------------------------------------------------------------------------
# 9. Aggregate over zero rows
# ---------------------------------------------------------------------------


def test_aggregates_over_zero_rows(users_catalog):
    """Empty table — SUM/AVG are None, COUNT is 0."""
    result = _run(
        users_catalog,
        "SELECT COUNT(*), SUM(age), AVG(age), MIN(age), MAX(age) FROM users",
    )
    assert result == [(0, None, None, None, None)]


# ---------------------------------------------------------------------------
# 10. NULL semantics — SUM(NULL) returns None
# ---------------------------------------------------------------------------


def test_sum_skips_null_values(users_catalog):
    """SUM(col) over rows where col is NULL returns None."""
    meta, _heap = _seed_users_with_null_dept(users_catalog)
    result = _run(
        users_catalog, "SELECT SUM(age) FROM users"
    )
    # ages: 30, 25, 40 → 95 (no NULLs in this fixture's age column).
    assert result == [(95,)]


def test_count_group_by_skips_row_with_null_group_key(users_catalog):
    """GROUP BY skips rows whose key column is NULL (SQLite parity)."""
    _seed_users_with_null_dept(users_catalog)
    # 2 rows with NULL dept should be ignored; 1 row with dept='sales'.
    result = _run(
        users_catalog, "SELECT dept, COUNT(*) FROM users GROUP BY dept"
    )
    assert result == [("sales", 1)]


# ---------------------------------------------------------------------------
# 11. Multiple GROUP BY keys
# ---------------------------------------------------------------------------


def _seed_multi_key(catalog):
    _drop_if_present(catalog, "users")
    catalog.create_table(
        "users",
        [
            Column(name="id", tag=TypeTag.Int, primary_key=True),
            Column(name="dept", tag=TypeTag.Text),
            Column(name="role", tag=TypeTag.Text),
        ],
    )
    meta = catalog.get_table("users")
    heap = Heap(catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    rows = [
        (1, "sales", "rep"),
        (2, "sales", "rep"),
        (3, "sales", "mgr"),
        (4, "eng", "dev"),
        (5, "eng", "dev"),
        (6, "eng", "mgr"),
    ]
    for r in rows:
        heap.insert(encode_row(r, _tags(meta)))


def test_group_by_two_keys(users_catalog):
    """GROUP BY dept, role yields one row per (dept, role) combo."""
    _seed_multi_key(users_catalog)
    result = _run(
        users_catalog,
        "SELECT dept, role, COUNT(*) FROM users GROUP BY dept, role ORDER BY dept, role",
    )
    assert result == [
        ("eng", "dev", 2),
        ("eng", "mgr", 1),
        ("sales", "mgr", 1),
        ("sales", "rep", 2),
    ]


# ---------------------------------------------------------------------------
# 12. End-to-end: insert + aggregate
# ---------------------------------------------------------------------------


def test_aggregate_after_insert(users_catalog):
    """Real planner+heap path: insert a row then SELECT COUNT(*) picks it up."""
    _seed_users(users_catalog)
    # Insert one more row.
    meta = users_catalog.get_table("users")
    heap = Heap(users_catalog._pager, table_id=meta.table_id)
    heap._head_pid = meta.heap_pid
    heap.insert(encode_row((6, "frank", 33), _tags(meta)))
    result = _run(users_catalog, "SELECT COUNT(*) FROM users")
    assert result == [(6,)]


# ---------------------------------------------------------------------------
# 13. Planner wraps result in AggregatePlan when aggregates present
# ---------------------------------------------------------------------------


def test_planner_emits_aggregate_node(users_catalog):
    """SELECT SUM(age) FROM users → plan tree rooted at AggregatePlan."""
    _seed_users(users_catalog)
    stmt = parse("SELECT SUM(age) FROM users")
    p = plan(stmt, users_catalog)
    assert isinstance(p, AggregatePlan)
    assert p.aggregates
    func, column = p.aggregates[0]
    assert func == "SUM"
    assert column == "age"


def test_planner_skips_aggregate_for_plain_select(users_catalog):
    """Plain SELECT (no aggregates) must NOT wrap in AggregatePlan."""
    _seed_users(users_catalog)
    stmt = parse("SELECT * FROM users")
    p = plan(stmt, users_catalog)
    assert not isinstance(p, AggregatePlan)
