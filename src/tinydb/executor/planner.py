"""AST → Plan tree translation.

T-5.1 implements the planner shape only — actual data flow lives in
T-5.2..5.6.  The planner is pure: it consults the catalog for schema
metadata and returns an immutable :class:`Plan` tree.

Validation
----------
* :class:`UnknownTableError`  — a referenced table is not in the catalog
* :class:`UnknownColumnError` — a referenced column is not in the table

Index selection
---------------
``_try_index_plan`` is a stub for T-5.3; today it always returns
``None`` so the planner falls through to ``SeqScan + Filter``.  The
hook is in place so a future commit only has to fill in the body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from tinydb.errors import TinydbError
from tinydb.executor.ops import (
    Delete as DeletePlan,
    Filter,
    IndexScan,
    Insert as InsertPlan,
    Plan,
    Project,
    SeqScan,
    Sort,
    Update as UpdatePlan,
)
from tinydb.sql.ast import (
    Aggregate,
    BinaryOp,
    ColumnRef,
    Delete as DeleteStmt,
    Expr,
    Insert as InsertStmt,
    Literal,
    OrderBy,
    Select,
    Star,
    Statement,
    TypedLiteral,
    UnaryOp,
    Update as UpdateStmt,
)
from tinydb.storage.catalog import Catalog, TableMeta


# ---------------------------------------------------------------------------
# Errors + Executor placeholder
# ---------------------------------------------------------------------------


class UnknownTableError(TinydbError):
    """A statement referenced a table that is not in the catalog."""


class UnknownColumnError(TinydbError):
    """A statement referenced a column that does not exist in the table."""


@dataclass
class Executor:
    """T-5.1 placeholder.  T-5.2 wires the real row-producing dispatch."""

    catalog: Catalog

    def execute(self, plan: Plan) -> list:
        raise NotImplementedError("T-5.2 will implement actual execution")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def plan(stmt: Statement, catalog: Catalog) -> Plan:
    """Lower ``stmt`` (an AST node) into a :class:`Plan` tree."""
    if isinstance(stmt, Select):
        return _plan_select(stmt, catalog)
    if isinstance(stmt, InsertStmt):
        return _plan_insert(stmt, catalog)
    if isinstance(stmt, UpdateStmt):
        return _plan_update(stmt, catalog)
    if isinstance(stmt, DeleteStmt):
        return _plan_delete(stmt, catalog)
    raise NotImplementedError(
        f"planner does not handle DDL statement: {type(stmt).__name__}"
    )


# ---------------------------------------------------------------------------
# Select
# ---------------------------------------------------------------------------


def _plan_select(stmt: Select, catalog: Catalog) -> Plan:
    meta = _require_table(stmt.table, catalog)

    # Source: SeqScan by default; IndexScan when _try_index_plan succeeds.
    src: Plan = SeqScan(table=meta.name)
    if (index_plan := _try_index_plan(stmt.where, meta)) is not None:
        src = index_plan

    # Wrap in Filter when a WHERE clause is present.
    if stmt.where is not None:
        _validate_expr_columns(stmt.where, meta)
        src = Filter(src=src, predicate=stmt.where)

    # Wrap in Project (including SELECT * for uniform executor dispatch).
    src = Project(src=src, columns=_project_columns(stmt, meta))

    # Wrap in Sort for ORDER BY / LIMIT / OFFSET.  Empty keys with a
    # limit is legal — T-5.4 treats empty keys as identity order.
    if stmt.order_by or stmt.limit is not None or stmt.offset:
        keys = [(ob.column, ob.descending) for ob in stmt.order_by]
        known = set(meta_column_names(meta))
        for col, _ in keys:
            if col not in known:
                raise UnknownColumnError(col)
        src = Sort(src=src, keys=keys, limit=stmt.limit, offset=stmt.offset or 0)

    # GROUP BY / aggregate — T-5.1 only constructs the plan shape;
    # T-5.6 will dispatch on the presence of aggregates at execute time.
    if stmt.group_by:
        known = set(meta_column_names(meta))
        for col in stmt.group_by:
            if col not in known:
                raise UnknownColumnError(col)

    return src


def _project_columns(stmt: Select, meta: TableMeta) -> list:
    """Resolve a SELECT list to a flat list of result-row column names.

    ``SELECT *`` expands to every declared column; explicit ColumnRef /
    Aggregate / literal / expression items each get a stable label so
    the executor can address result columns by name.
    """
    all_names = meta_column_names(meta)
    if len(stmt.columns) == 1 and isinstance(stmt.columns[0], Star):
        return list(all_names)
    out: list = []
    for item in stmt.columns:
        if isinstance(item, Star):
            for c in all_names:
                if c not in out:
                    out.append(c)
        elif isinstance(item, ColumnRef):
            if item.name not in all_names:
                raise UnknownColumnError(item.name)
            if item.name not in out:
                out.append(item.name)
        elif isinstance(item, Aggregate):
            out.append(f"{item.func}({item.column})")
        elif isinstance(item, Literal):
            out.append(f"L:{item.value!r}")
        elif isinstance(item, TypedLiteral):
            out.append(f"L[{item.tag.name}]:{item.value!r}")
        else:
            # BinaryOp / UnaryOp / unknown: stable synthetic name.
            out.append(type(item).__name__)
    return out


# ---------------------------------------------------------------------------
# DML statements
# ---------------------------------------------------------------------------


def _plan_insert(stmt: InsertStmt, catalog: Catalog) -> Plan:
    _require_table(stmt.table, catalog)
    # Forward the multi-row ``values`` tuple; executor iterates it.
    return InsertPlan(table=stmt.table, values=stmt.values)


def _plan_update(stmt: UpdateStmt, catalog: Catalog) -> Plan:
    meta = _require_table(stmt.table, catalog)
    known = set(meta_column_names(meta))
    assignments = []
    for a in stmt.set_clauses:
        if a.column not in known:
            raise UnknownColumnError(a.column)
        assignments.append((a.column, a.value))
    if stmt.where is not None:
        _validate_expr_columns(stmt.where, meta)
    return UpdatePlan(
        table=stmt.table, assignments=assignments, predicate=stmt.where
    )


def _plan_delete(stmt: DeleteStmt, catalog: Catalog) -> Plan:
    meta = _require_table(stmt.table, catalog)
    if stmt.where is not None:
        _validate_expr_columns(stmt.where, meta)
    return DeletePlan(table=stmt.table, predicate=stmt.where)


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------


def _require_table(name: str, catalog: Catalog) -> TableMeta:
    try:
        return catalog.get_table(name)
    except KeyError as exc:
        raise UnknownTableError(name) from exc


def meta_column_names(meta: TableMeta) -> list:
    return [c.name for c in meta.columns]


def _validate_expr_columns(expr: Expr, meta: TableMeta) -> None:
    """Walk an Expr tree; raise UnknownColumnError on any unknown ColumnRef."""
    _walk_expr(expr, set(meta_column_names(meta)))


def _walk_expr(expr: Any, known: set) -> None:
    if isinstance(expr, ColumnRef):
        if expr.name not in known:
            raise UnknownColumnError(expr.name)
    elif isinstance(expr, BinaryOp):
        _walk_expr(expr.left, known)
        _walk_expr(expr.right, known)
    elif isinstance(expr, UnaryOp):
        _walk_expr(expr.operand, known)
    # Literal / TypedLiteral / Star / Aggregate — nothing to validate.


# ---------------------------------------------------------------------------
# Index-plan stub (T-5.3 fills in)
# ---------------------------------------------------------------------------


def _try_index_plan(
    predicate: Optional[Expr], meta: TableMeta
) -> Optional[IndexScan]:
    """Stub for T-5.3 index selection.  Always returns ``None`` today."""
    return None


__all__ = ["Executor", "plan", "UnknownTableError", "UnknownColumnError"]