"""T-5.1 planner tests — AST → Plan tree translation.

Each test arranges a tiny schema in the catalog, parses a SQL string
via :func:`tinydb.sql.parse`, calls :func:`tinydb.executor.plan`, and
asserts the plan tree shape via :func:`isinstance` walks.  No
``.execute()`` is invoked — T-5.1 only defines the plan tree shape.
"""

from __future__ import annotations

import pytest

from tinydb.executor.ops import (
    Delete as DeletePlan,
    Filter,
    IndexScan,
    Insert as InsertPlan,
    Limit,
    Plan,
    Project,
    SeqScan,
    Sort,
    Update as UpdatePlan,
)
from tinydb.executor.planner import (
    Executor,
    UnknownColumnError,
    UnknownTableError,
    plan,
)
from tinydb.sql.parser import parse_dml_string as parse


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unwrap_filter(p: Plan) -> Plan:
    """Assert ``p`` is a Filter and return its source."""
    assert isinstance(p, Filter)
    return p.src


# ---------------------------------------------------------------------------
# 1. SELECT * FROM users
# ---------------------------------------------------------------------------


def test_select_star_from_users(users_catalog):
    """SELECT * FROM users → SeqScan("users") wrapped in auto-Star Project."""
    stmt = parse("SELECT * FROM users")
    p = plan(stmt, users_catalog)

    # outer Project wrapping a SeqScan
    assert isinstance(p, Project)
    assert list(p.columns) == ["id", "name", "age"]
    assert isinstance(p.src, SeqScan)
    assert p.src.table == "users"


# ---------------------------------------------------------------------------
# 2. SELECT id, name FROM users
# ---------------------------------------------------------------------------


def test_select_specific_columns(users_catalog):
    """SELECT id, name FROM users → SeqScan + Project(['id','name'])."""
    stmt = parse("SELECT id, name FROM users")
    p = plan(stmt, users_catalog)

    assert isinstance(p, Project)
    assert list(p.columns) == ["id", "name"]
    assert isinstance(p.src, SeqScan)
    assert p.src.table == "users"


# ---------------------------------------------------------------------------
# 3. SELECT * FROM users WHERE id = 1
# ---------------------------------------------------------------------------


def test_select_star_with_where(users_catalog):
    """SELECT * FROM users WHERE id = 1 → Project(Filter(SeqScan, expr))."""
    from tinydb.sql.ast import BinaryOp

    stmt = parse("SELECT * FROM users WHERE id = 1")
    p = plan(stmt, users_catalog)

    # outer Project (auto-Star)
    assert isinstance(p, Project)
    # next layer is Filter wrapping SeqScan
    inner = _unwrap_filter(p.src)
    assert isinstance(inner, SeqScan)
    assert inner.table == "users"
    # predicate lives on the Filter node
    assert isinstance(p.src.predicate, BinaryOp)
    assert p.src.predicate.op == "="


# ---------------------------------------------------------------------------
# 4. SELECT id FROM users WHERE age > 18 ORDER BY name
# ---------------------------------------------------------------------------


def test_select_with_where_order_by(users_catalog):
    """SELECT id FROM users WHERE age > 18 ORDER BY name → Sort(Project(Filter(SeqScan)))."""
    stmt = parse("SELECT id FROM users WHERE age > 18 ORDER BY name")
    p = plan(stmt, users_catalog)

    # outer Sort wraps everything
    assert isinstance(p, Sort)
    assert list(p.keys) == [("name", False)]  # ASC
    # inside Sort, a Project(['id'])
    proj = p.src
    assert isinstance(proj, Project)
    assert list(proj.columns) == ["id"]
    # inside Project, the Filter
    filt = proj.src
    assert isinstance(filt, Filter)
    assert isinstance(filt.src, SeqScan)
    assert filt.src.table == "users"


# ---------------------------------------------------------------------------
# 5. SELECT id FROM users LIMIT 5 OFFSET 2
# ---------------------------------------------------------------------------


def test_select_limit_offset_no_order_by(users_catalog):
    """SELECT id FROM users LIMIT 5 OFFSET 2 → Limit(Project(SeqScan))."""
    stmt = parse("SELECT id FROM users LIMIT 5 OFFSET 2")
    p = plan(stmt, users_catalog)

    # outer Limit (no ORDER BY → no Sort wrapper)
    assert isinstance(p, Limit)
    assert p.limit == 5
    assert p.offset == 2
    # inside Limit, Project(['id']) wrapping SeqScan
    proj = p.src
    assert isinstance(proj, Project)
    assert list(proj.columns) == ["id"]
    assert isinstance(proj.src, SeqScan)
    assert proj.src.table == "users"


# ---------------------------------------------------------------------------
# 6. INSERT INTO users VALUES (1, 'a', 30)
# ---------------------------------------------------------------------------


def test_insert_plan_shape(users_catalog):
    """INSERT INTO users VALUES (1, 'a', 30) → InsertPlan with values tuple."""
    stmt = parse("INSERT INTO users VALUES (1, 'a', 30)")
    p = plan(stmt, users_catalog)

    assert isinstance(p, InsertPlan)
    assert p.table == "users"
    assert p.values == ((1, "a", 30),)


# ---------------------------------------------------------------------------
# 7. UPDATE users SET name='b' WHERE id = 1
# ---------------------------------------------------------------------------


def test_update_plan_with_predicate(users_catalog):
    """UPDATE users SET name='b' WHERE id = 1 → UpdatePlan with predicate."""
    from tinydb.sql.ast import BinaryOp

    stmt = parse("UPDATE users SET name = 'b' WHERE id = 1")
    p = plan(stmt, users_catalog)

    assert isinstance(p, UpdatePlan)
    assert p.table == "users"
    assert p.predicate is not None
    assert isinstance(p.predicate, BinaryOp)
    assert p.predicate.op == "="
    assert len(p.assignments) == 1
    col, _expr = p.assignments[0]
    assert col == "name"


# ---------------------------------------------------------------------------
# 8. DELETE FROM users WHERE id = 1
# ---------------------------------------------------------------------------


def test_delete_plan_with_predicate(users_catalog):
    """DELETE FROM users WHERE id = 1 → DeletePlan with predicate."""
    from tinydb.sql.ast import BinaryOp

    stmt = parse("DELETE FROM users WHERE id = 1")
    p = plan(stmt, users_catalog)

    assert isinstance(p, DeletePlan)
    assert p.table == "users"
    assert isinstance(p.predicate, BinaryOp)
    assert p.predicate.op == "="


# ---------------------------------------------------------------------------
# 9. Unknown table → UnknownTableError
# ---------------------------------------------------------------------------


def test_unknown_table_raises(users_catalog):
    """Referencing an unregistered table raises UnknownTableError."""
    stmt = parse("SELECT * FROM ghost")
    with pytest.raises(UnknownTableError):
        plan(stmt, users_catalog)


# ---------------------------------------------------------------------------
# 10. Unknown column in WHERE → UnknownColumnError
# ---------------------------------------------------------------------------


def test_unknown_column_in_where_raises(users_catalog):
    """A column referenced in WHERE that is not in the schema raises UnknownColumnError."""
    stmt = parse("SELECT * FROM users WHERE color = 'red'")
    with pytest.raises(UnknownColumnError):
        plan(stmt, users_catalog)


# ---------------------------------------------------------------------------
# 11. Index-scan stub path — _try_index_plan called, returns None → SeqScan+Filter
# ---------------------------------------------------------------------------


def test_try_index_plan_called_but_returns_none(users_catalog, monkeypatch):
    """When _try_index_plan is invoked, it must be consulted and return None
    (T-5.3 will replace the stub).  The plan still lowers cleanly to a
    SeqScan+Filter shape so executor dispatch is unaffected.
    """
    from tinydb.executor import planner as planner_mod

    calls = []

    def spy(predicate, table_meta, indexer=None):
        calls.append((predicate, table_meta.name))
        return None

    monkeypatch.setattr(planner_mod, "_try_index_plan", spy)

    stmt = parse("SELECT * FROM users WHERE id = 1")
    p = plan(stmt, users_catalog)

    assert calls, "_try_index_plan must be consulted for a filterable predicate"
    # the resulting plan still has Filter + SeqScan
    assert isinstance(p, Project)
    inner = _unwrap_filter(p.src)
    assert isinstance(inner, SeqScan)


# ---------------------------------------------------------------------------
# 12. GROUP BY with aggregate → plan() returns *some* Plan (T-5.6 executes it)
# ---------------------------------------------------------------------------


def test_group_by_aggregate_plan_constructs(users_catalog):
    """GROUP BY + aggregate constructs a plan without raising.

    Execution is out of scope for T-5.1 — the planner only has to
    produce a tree; downstream T-5.6 will run it.
    """
    stmt = parse("SELECT COUNT(*), name FROM users GROUP BY name")
    p = plan(stmt, users_catalog)
    assert isinstance(p, Plan)


# ---------------------------------------------------------------------------
# Bonus: Executor symbol + IndexScan dataclass shape
# ---------------------------------------------------------------------------


def test_executor_symbol_exists(users_catalog):
    """Executor is exposed with .catalog attribute and an .execute() method."""
    from tinydb.executor.planner import Executor

    ex = Executor(catalog=users_catalog)
    assert ex.catalog is users_catalog
    # T-5.2: SELECT execution is now implemented; the executor must
    # return a list (empty here since the users table has no rows yet).
    stmt = parse("SELECT * FROM users")
    p = plan(stmt, users_catalog)
    result = ex.execute(p)
    assert isinstance(result, list)


def test_index_scan_dataclass_shape():
    """IndexScan is a frozen Plan subclass with the documented fields."""
    scan = IndexScan(
        table="users",
        index="idx_users_id",
        lo=1,
        hi=10,
        lo_inclusive=True,
        hi_inclusive=False,
    )
    assert scan.op_name == "IndexScan"
    assert scan.table == "users"
    assert scan.index == "idx_users_id"
    assert scan.lo == 1
    assert scan.hi == 10
    assert scan.lo_inclusive is True
    assert scan.hi_inclusive is False


def test_limit_is_not_a_sort_alias():
    """After T-5.4, Limit is its own dataclass — no longer a Sort alias."""
    assert Limit is not Sort