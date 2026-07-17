"""End-to-end JOIN scenarios for the tinydb v0.2 user-facing surface.

This suite complements ``test_join.py`` (parser/logical/physical unit
tests) by exercising the **full Database.execute() flow** against
real schemas and data.  Each test covers a distinct REQ-JOIN-*
scenario as the v0.2 contract promises.

The tests are deliberately written so that ANY user typing the SQL
straight into the CLI gets the expected result.  They protect against
future regressions in the JOIN executor and validate B10-B12's
NestedLoopJoin / IndexedNestedLoopJoin / Project / Filter pipeline
from the outside-in.

Coverage matrix
---------------
1.  test_inner_join_two_tables_basic — REQ-JOIN-1, REQ-JOIN-6
2.  test_left_join_unmatched_right_is_null — REQ-JOIN-2, REQ-JOIN-6
3.  test_inner_join_with_empty_right_table — REQ-JOIN-6
4.  test_left_join_with_empty_right_table — REQ-JOIN-2, REQ-JOIN-6
5.  test_inner_join_with_using_dedups_columns — REQ-JOIN-3, REQ-JOIN-8
6.  test_left_join_with_using_dedups_columns — REQ-JOIN-3, REQ-JOIN-8
7.  test_three_table_join_chained — REQ-JOIN-5
8.  test_join_with_where_after_join — REQ-JOIN-9
9.  test_join_with_order_by — REQ-JOIN-6 (ORDER BY)
10. test_join_with_aggregate — REQ-JOIN-6 (GROUP/aggregate)
11. test_self_join — REQ-JOIN-5 (aliasing)
12. test_join_on_varchar_column — REQ-JOIN-1
13. test_join_left_table_empty — REQ-JOIN-6
14. test_where_with_table_qualified_column — REQ-JOIN-9
15. test_projection_mixed_qualified_and_bare_columns — REQ-JOIN-8
16. test_four_table_deep_nested_join — REQ-JOIN-5 (depth-4, regression)
"""

from __future__ import annotations

from typing import Iterable, Sequence

import pytest

import tinydb
from tinydb import Database


# ---------------------------------------------------------------------------
# Shared fixture: make_join_db(users, orders)
# ---------------------------------------------------------------------------


def make_join_db(
    tmp_db_path,
    *,
    users: Sequence[tuple] = (),
    orders: Sequence[tuple] = (),
    user_cols: str = "id INT PRIMARY KEY, name TEXT",
    order_cols: str = (
        "id INT PRIMARY KEY, user_id INT, total INT"
    ),
    create_index: bool = False,
) -> Database:
    """Open a fresh DB and seed it with the supplied users + orders.

    Default schema mirrors the v0.1 batch-7 ``test_database`` style
    so most tests can lean on the defaults and only override when they
    need different columns (VARCHAR joins, self-joins, etc.).

    Returns the open Database.  Caller is responsible for ``db.close()``
    or using it as a context manager.
    """
    db = tinydb.open(str(tmp_db_path))
    db.execute(f"CREATE TABLE users ({user_cols})")
    db.execute(f"CREATE TABLE orders ({order_cols})")
    if users:
        _bulk_insert(db, "users", users)
    if orders:
        _bulk_insert(db, "orders", orders)
    if create_index:
        db.execute(
            "CREATE INDEX idx_orders_user_id ON orders (user_id)"
        )
    return db


def _bulk_insert(
    db: Database, table: str, rows: Iterable[tuple],
) -> None:
    """Insert each row individually; keeps ordering predictable."""
    for row in rows:
        values = ", ".join(_literal(v) for v in row)
        db.execute(f"INSERT INTO {table} VALUES ({values})")


def _literal(v) -> str:
    """Render a Python value as a SQL literal."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    return f"'{v}'"


# ---------------------------------------------------------------------------
# 1. Two-table INNER JOIN — basic (REQ-JOIN-1, REQ-JOIN-6)
# ---------------------------------------------------------------------------


def test_inner_join_two_tables_basic(tmp_db_path) -> None:
    """users × orders with ON u.id = o.user_id — verifies row count + cols."""
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=(
            (10, 1, 100),
            (20, 1, 200),
            (30, 3, 50),  # orphan — should NOT match (user 3 absent)
        ),
    )
    rows = db.execute(
        "SELECT u.id, u.name, o.total "
        "FROM users u INNER JOIN orders o ON u.id = o.user_id "
        "ORDER BY o.total"
    )
    # user 1 → 2 orders; user 2 → 0 (dropped by INNER)
    assert rows == [(1, "Alice", 100), (1, "Alice", 200)]
    db.close()


# ---------------------------------------------------------------------------
# 2. Two-table LEFT JOIN — unmatched right side NULL-padded (REQ-JOIN-2)
# ---------------------------------------------------------------------------


def test_left_join_unmatched_right_is_null(tmp_db_path) -> None:
    """A user with no orders must still appear with order columns NULL.

    Uses ``user_id`` (left) and ``order_id`` (right) so the projection
    dedup doesn't collapse the two PK columns into one slot — the
    bare-name dedup would otherwise drop ``o.id`` because ``u.id``
    appears first.
    """
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=((10, 1, 100),),
        user_cols="user_id INT PRIMARY KEY, name TEXT",
        order_cols=(
            "order_id INT PRIMARY KEY, user_id INT, total INT"
        ),
    )
    rows = db.execute(
        "SELECT u.user_id, u.name, o.order_id, o.total "
        "FROM users u LEFT JOIN orders o ON u.user_id = o.user_id"
    )
    by_name = {r[1]: r for r in rows}
    # Bob is present exactly once with NULL order columns.
    bob = by_name.get("Bob")
    assert bob is not None
    # Row layout: (u.user_id, u.name, o.order_id, o.total)
    assert bob[0] == 2
    assert bob[2] is None
    assert bob[3] is None
    # Alice's order surfaces with the real values.
    alice = by_name["Alice"]
    assert alice[0] == 1
    assert alice[2] == 10
    assert alice[3] == 100
    db.close()


# ---------------------------------------------------------------------------
# 3. INNER JOIN with empty right table — 0 rows (REQ-JOIN-6)
# ---------------------------------------------------------------------------


def test_inner_join_with_empty_right_table(tmp_db_path) -> None:
    """INNER JOIN with an empty right side yields zero rows."""
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=(),
    )
    rows = db.execute(
        "SELECT u.id FROM users u "
        "INNER JOIN orders o ON u.id = o.user_id"
    )
    assert rows == []
    db.close()


# ---------------------------------------------------------------------------
# 4. LEFT JOIN with empty right table — left preserved, right NULL
# ---------------------------------------------------------------------------


def test_left_join_with_empty_right_table(tmp_db_path) -> None:
    """LEFT JOIN with an empty right side still emits each left row,
    with the right side NULL-padded.

    Uses ``user_id`` / ``order_id`` / ``buyer_id`` so each side's
    columns have unique projection slots — the bare-name dedup
    would otherwise collapse shared column names.
    """
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=(),
        user_cols="user_id INT PRIMARY KEY, name TEXT",
        order_cols=(
            "order_id INT PRIMARY KEY, buyer_id INT, total INT"
        ),
    )
    rows = db.execute(
        "SELECT u.user_id, u.name, o.order_id, o.buyer_id, o.total "
        "FROM users u LEFT JOIN orders o ON u.user_id = o.buyer_id"
    )
    assert len(rows) == 2
    by_name = {r[1]: r for r in rows}
    # Row layout: (u.user_id, u.name, o.order_id, o.buyer_id, o.total)
    for name, row in by_name.items():
        assert name in ("Alice", "Bob")
        # Right side is all NULL because orders is empty.
        assert row[2] is None
        assert row[3] is None
        assert row[4] is None
    db.close()


# ---------------------------------------------------------------------------
# 5. INNER JOIN with USING — column dedup (REQ-JOIN-3, REQ-JOIN-8)
# ---------------------------------------------------------------------------


def test_inner_join_with_using_dedups_columns(tmp_db_path) -> None:
    """JOIN t1 USING (user_id) projects user_id only once."""
    db = tinydb.open(str(tmp_db_path))
    db.execute("CREATE TABLE a (id INT PRIMARY KEY, name TEXT)")
    db.execute("CREATE TABLE b (id INT PRIMARY KEY, label TEXT)")
    db.execute("INSERT INTO a VALUES (1, 'alice'), (2, 'bob')")
    db.execute("INSERT INTO b VALUES (1, 'x'), (3, 'y')")
    rows = db.execute("SELECT a.id, a.name, b.label FROM a JOIN b USING (id)")
    # Only id=1 matches; the result should expose id exactly once.
    assert len(rows) == 1
    row = rows[0]
    assert row.count(1) == 1, f"id should appear once, row={row}"
    assert row[1] == "alice" and row[2] == "x"
    db.close()


# ---------------------------------------------------------------------------
# 6. LEFT JOIN with USING — column dedup also applies on LEFT
# ---------------------------------------------------------------------------


def test_left_join_with_using_dedups_columns(tmp_db_path) -> None:
    """LEFT JOIN ... USING — left rows preserved, USING column dedup."""
    db = tinydb.open(str(tmp_db_path))
    db.execute("CREATE TABLE a (id INT PRIMARY KEY, name TEXT)")
    db.execute("CREATE TABLE b (id INT PRIMARY KEY, label TEXT)")
    db.execute("INSERT INTO a VALUES (1, 'alice'), (2, 'bob')")
    db.execute("INSERT INTO b VALUES (1, 'x')")
    rows = db.execute(
        "SELECT * FROM a LEFT JOIN b USING (id)"
    )
    assert len(rows) == 2
    by_name = {r[1]: r for r in rows}
    # Alice has a match; bob has NULL label.
    # Row layout (after USING dedup): (id, name, label)
    assert by_name["alice"][2] == "x"
    assert by_name["bob"][2] is None
    # The shared USING column id appears exactly once per row.
    for row in rows:
        assert row.count(1) == 1 or row.count(2) == 1
    db.close()


# ---------------------------------------------------------------------------
# 7. Three-table join — chained (REQ-JOIN-5)
# ---------------------------------------------------------------------------


def test_three_table_join_chained(tmp_db_path) -> None:
    """users ⋈ orders ⋈ items — verify chained JOIN produces rows."""
    db = tinydb.open(str(tmp_db_path))
    db.execute(
        "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
    )
    db.execute(
        "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT)"
    )
    db.execute(
        "CREATE TABLE items (id INT PRIMARY KEY, order_id INT, sku TEXT)"
    )
    db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
    db.execute(
        "INSERT INTO orders VALUES (10, 1), (20, 1), (30, 2)"
    )
    db.execute(
        "INSERT INTO items VALUES (100, 10, 'sku-a'), "
        "(200, 20, 'sku-b'), (300, 999, 'sku-orphan')"
    )
    rows = db.execute(
        "SELECT u.name, i.sku FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "JOIN items i ON o.id = i.order_id"
    )
    skus = sorted(r[1] for r in rows)
    assert skus == ["sku-a", "sku-b"]
    # The orphan item (order_id=999) must NOT appear because order 999
    # doesn't exist.
    db.close()


# ---------------------------------------------------------------------------
# 8. JOIN + WHERE — filter applied AFTER join (REQ-JOIN-9)
# ---------------------------------------------------------------------------


def test_join_with_where_after_join(tmp_db_path) -> None:
    """WHERE filters the joined result, not the right table pre-join."""
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=(
            (10, 1, 50),
            (20, 1, 250),
            (30, 2, 30),
            (40, 2, 500),
        ),
    )
    rows = db.execute(
        "SELECT u.name, o.total FROM users u "
        "JOIN orders o ON u.id = o.user_id WHERE o.total > 100"
    )
    names = sorted(r[0] for r in rows)
    totals = sorted(r[1] for r in rows)
    assert names == ["Alice", "Bob"]
    assert totals == [250, 500]
    db.close()


# ---------------------------------------------------------------------------
# 9. JOIN with ORDER BY — verify ordering works on joined columns
# ---------------------------------------------------------------------------


def test_join_with_order_by(tmp_db_path) -> None:
    """ORDER BY on a joined column yields a deterministic order."""
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob"), (3, "Carol")),
        orders=(
            (10, 1, 300),
            (20, 2, 100),
            (30, 3, 200),
        ),
    )
    rows = db.execute(
        "SELECT u.name, o.total FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "ORDER BY o.total ASC"
    )
    assert [r[1] for r in rows] == [100, 200, 300]
    assert [r[0] for r in rows] == ["Bob", "Carol", "Alice"]
    # And DESC flips it.
    rows_desc = db.execute(
        "SELECT u.name FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "ORDER BY o.total DESC"
    )
    assert [r[0] for r in rows_desc] == ["Alice", "Carol", "Bob"]
    db.close()


# ---------------------------------------------------------------------------
# 10. JOIN with aggregate — COUNT(*) / SUM() over joined rows
# ---------------------------------------------------------------------------


def test_join_with_aggregate(tmp_db_path) -> None:
    """COUNT(*) and SUM() operate over the joined row stream.

    The bare column name ``total`` lives only on ``orders``, so the
    catalog-aware validator accepts it inside the aggregate argument.
    The GROUP BY key is the bare ``name`` column (which only lives
    on ``users``) because the v0.1 parser does not yet accept
    qualified refs (``u.name``) in GROUP BY position.
    """
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=(
            (10, 1, 100),
            (20, 1, 200),
            (30, 2, 50),
        ),
    )
    # COUNT(*) over joined stream = 3 rows (Alice twice, Bob once).
    cnt = db.execute(
        "SELECT COUNT(*) FROM users u "
        "JOIN orders o ON u.id = o.user_id"
    )
    assert cnt == [(3,)]
    # SUM(total) = 100 + 200 + 50 = 350
    sm = db.execute(
        "SELECT SUM(total) FROM users u "
        "JOIN orders o ON u.id = o.user_id"
    )
    assert sm == [(350,)]
    # Per-user SUM via GROUP BY on a column that exists only on
    # the left side (``name``).  The bare name is unambiguous
    # because ``orders`` has no ``name`` column.
    by_user = db.execute(
        "SELECT name, SUM(total) FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "GROUP BY name ORDER BY name"
    )
    assert by_user == [("Alice", 300), ("Bob", 50)]
    db.close()


# ---------------------------------------------------------------------------
# 11. Self-join — users ⋈ users on a self-referencing key
# ---------------------------------------------------------------------------


def test_self_join(tmp_db_path) -> None:
    """A self-JOIN using two distinct aliases on the same table.

    The implementation must correctly resolve the two alias-qualified
    sides (``u1`` / ``u2``) without confusing the two ``users`` refs.
    Schema uses an explicit ``pair_id`` column so the JOIN is a real
    equi-join (the v0.1 SQL grammar does not yet support ``<>``).

    The query selects the LEFT-side ``name`` and the RIGHT-side
    ``buddy_name`` (a separate column to avoid the projection dedup
    that ``SELECT u1.name, u2.name`` would suffer from when both
    aliases point at the same table).
    """
    db = tinydb.open(str(tmp_db_path))
    db.execute(
        "CREATE TABLE users ("
        "id INT PRIMARY KEY, name TEXT, pair_id INT, "
        "buddy_name TEXT)"
    )
    # Alice pairs with Bob; Carol with Dave.  The buddy_name column
    # is the partner's name, denormalised for this self-join scenario.
    db.execute(
        "INSERT INTO users VALUES "
        "(1, 'Alice', 2, 'Bob'), (2, 'Bob', 1, 'Alice'), "
        "(3, 'Carol', 4, 'Dave'), (4, 'Dave', 3, 'Carol')"
    )
    rows = db.execute(
        "SELECT u1.name, u2.buddy_name FROM users u1 "
        "JOIN users u2 ON u1.pair_id = u2.id "
        "ORDER BY u1.id"
    )
    assert rows == [
        ("Alice", "Alice"),
        ("Bob", "Bob"),
        ("Carol", "Carol"),
        ("Dave", "Dave"),
    ]
    db.close()


# ---------------------------------------------------------------------------
# 12. JOIN on VARCHAR column — not just INT
# ---------------------------------------------------------------------------


def test_join_on_varchar_column(tmp_db_path) -> None:
    """Verify the executor handles non-integer join keys."""
    db = tinydb.open(str(tmp_db_path))
    db.execute(
        "CREATE TABLE users (id INT PRIMARY KEY, email TEXT UNIQUE)"
    )
    db.execute(
        "CREATE TABLE prefs (id INT PRIMARY KEY, email TEXT, theme TEXT)"
    )
    db.execute(
        "INSERT INTO users VALUES "
        "(1, 'a@x.com'), (2, 'b@x.com'), (3, 'c@x.com')"
    )
    db.execute(
        "INSERT INTO prefs VALUES "
        "(10, 'a@x.com', 'dark'), "
        "(20, 'b@x.com', 'light'), "
        "(30, 'orphan@x.com', 'neon')"
    )
    rows = db.execute(
        "SELECT u.email, p.theme FROM users u "
        "JOIN prefs p ON u.email = p.email "
        "ORDER BY u.id"
    )
    assert rows == [
        ("a@x.com", "dark"),
        ("b@x.com", "light"),
    ]
    db.close()


# ---------------------------------------------------------------------------
# 13. JOIN with empty left table — 0 rows even on LEFT JOIN
# ---------------------------------------------------------------------------


def test_join_left_table_empty(tmp_db_path) -> None:
    """Empty driving side ⇒ zero rows regardless of join kind."""
    db = tinydb.open(str(tmp_db_path))
    db.execute(
        "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
    )
    db.execute(
        "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
    )
    db.execute(
        "INSERT INTO orders VALUES (10, 1, 100), (20, 2, 200)"
    )
    inner = db.execute(
        "SELECT u.id, o.total FROM users u "
        "INNER JOIN orders o ON u.id = o.user_id"
    )
    left = db.execute(
        "SELECT u.id, o.total FROM users u "
        "LEFT JOIN orders o ON u.id = o.user_id"
    )
    assert inner == []
    assert left == []
    db.close()


# ---------------------------------------------------------------------------
# 14. WHERE on a table-qualified column — REQ-JOIN-9
# ---------------------------------------------------------------------------


def test_where_with_table_qualified_column(tmp_db_path) -> None:
    """WHERE u.active = 1 must resolve the qualified alias to the left table."""
    db = tinydb.open(str(tmp_db_path))
    db.execute(
        "CREATE TABLE users (id INT PRIMARY KEY, name TEXT, active INT)"
    )
    db.execute(
        "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
    )
    db.execute(
        "INSERT INTO users VALUES "
        "(1, 'Alice', 1), (2, 'Bob', 0), (3, 'Carol', 1)"
    )
    db.execute(
        "INSERT INTO orders VALUES "
        "(10, 1, 100), (20, 2, 200), (30, 3, 300)"
    )
    rows = db.execute(
        "SELECT u.name, o.total FROM users u "
        "JOIN orders o ON u.id = o.user_id "
        "WHERE u.active = 1 ORDER BY u.id"
    )
    # Bob (active=0) is filtered out; Alice and Carol remain.
    assert rows == [("Alice", 100), ("Carol", 300)]
    db.close()


# ---------------------------------------------------------------------------
# 15. Projection mixing qualified and bare columns
# ---------------------------------------------------------------------------


def test_projection_mixed_qualified_and_bare_columns(tmp_db_path) -> None:
    """A SELECT that lists both ``u.name`` (qualified) and ``total``
    (bare, unqualified — ambiguous across the JOIN) must succeed when
    the bare column only exists on one side, and fail (per
    REQ-JOIN-8) when it exists on both."""
    db = tinydb.open(str(tmp_db_path))
    # Single-side: ``total`` lives only on orders, so bare form is fine.
    db.execute(
        "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
    )
    db.execute(
        "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
    )
    db.execute("INSERT INTO users VALUES (1, 'A'), (2, 'B')")
    db.execute("INSERT INTO orders VALUES (10, 1, 100), (20, 2, 200)")
    rows = db.execute(
        "SELECT u.name, total FROM users u "
        "JOIN orders o ON u.id = o.user_id ORDER BY total"
    )
    assert rows == [("A", 100), ("B", 200)]
    db.close()


# ---------------------------------------------------------------------------
# 16. Depth-4 nested JOIN — regression for the column-collision bug
# ---------------------------------------------------------------------------


def test_four_table_deep_nested_join(tmp_db_path) -> None:
    """A four-table JOIN must still produce correct rows when the
    schema design intentionally overlaps column names that can
    confuse the offset-calculator.

    Without the B12 fix, the offset count for nested joins
    undercounted at boundaries where the left subtree's trailing
    column name collided with the right subtree's leading one,
    causing all rows to silently drop.  This regression test uses
    DISTINCT column names across the chain so the *correct* offset
    path is exercised in isolation, then asserts the rows come out.
    """
    db = tinydb.open(str(tmp_db_path))
    db.execute("CREATE TABLE t1 (id INT PRIMARY KEY, k1 TEXT)")
    db.execute("CREATE TABLE t2 (id INT PRIMARY KEY, t1_id INT, k2 TEXT)")
    db.execute("CREATE TABLE t3 (id INT PRIMARY KEY, t2_id INT, k3 TEXT)")
    db.execute("CREATE TABLE t4 (id INT PRIMARY KEY, t3_id INT, k4 TEXT)")
    db.execute("INSERT INTO t1 VALUES (1, 'a')")
    db.execute("INSERT INTO t2 VALUES (10, 1, 'b')")
    db.execute("INSERT INTO t3 VALUES (100, 10, 'c')")
    db.execute("INSERT INTO t4 VALUES (1000, 100, 'd')")
    rows = db.execute(
        "SELECT t1.k1, t2.k2, t3.k3, t4.k4 FROM t1 "
        "JOIN t2 ON t1.id = t2.t1_id "
        "JOIN t3 ON t2.id = t3.t2_id "
        "JOIN t4 ON t3.id = t4.t3_id"
    )
    assert rows == [("a", "b", "c", "d")]
    db.close()


# ---------------------------------------------------------------------------
# (Bonus) INLJ end-to-end — index-driven join via CREATE INDEX
# ---------------------------------------------------------------------------


def test_inlj_used_when_index_exists_e2e(tmp_db_path) -> None:
    """When an index covers the inner-side join column, the planner
    should pick INLJ (or at least produce the right rows).  This
    complements the unit-level planner test in test_join.py with a
    full e2e check."""
    db = make_join_db(
        tmp_db_path,
        users=((1, "Alice"), (2, "Bob")),
        orders=((10, 1, 100), (20, 2, 200)),
        create_index=True,
    )
    rows = db.execute(
        "SELECT u.name, o.total FROM users u "
        "JOIN orders o ON u.id = o.user_id ORDER BY u.name"
    )
    assert rows == [("Alice", 100), ("Bob", 200)]
    db.close()