"""AST → Plan tree translation.

T-5.1 implements the planner shape; T-5.2 adds the
``Project(..., items=...)`` argument so the executor can evaluate
non-trivial projections; T-5.3 adds the index selection hook.

Validation
----------
* :class:`UnknownTableError`  — a referenced table is not in the catalog
* :class:`UnknownColumnError` — a referenced column is not in the table

Index selection
---------------
``_try_index_plan`` extracts a single-column :class:`IndexablePredicate`
from the WHERE clause; when an index covers that column it returns an
:class:`IndexScan`, otherwise ``None`` so the caller falls back to
``SeqScan + Filter``.
"""

from __future__ import annotations

from typing import Any, Optional

from tinydb.errors import TinydbError
from tinydb.executor.executor import Executor  # re-export
from tinydb.executor.index_plan import extract_indexable
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
from tinydb.index.manager import IndexManager
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
    Update as UpdateStmt,
)
from tinydb.storage.catalog import Catalog, IndexMeta, TableMeta


class UnknownTableError(TinydbError):
    """A statement referenced a table that is not in the catalog."""


class UnknownColumnError(TinydbError):
    """A statement referenced a column that does not exist in the table."""


def plan(
    stmt: Statement,
    catalog: Catalog,
    indexer: Optional[IndexManager] = None,
) -> Plan:
    """Lower ``stmt`` (an AST node) into a :class:`Plan` tree.

    ``indexer`` is optional; when provided the planner picks
    :class:`IndexScan` over :class:`SeqScan` whenever a single-column
    equality or range predicate matches an existing B-tree index.
    Without ``indexer`` the planner always falls back to SeqScan+Filter.
    """
    if isinstance(stmt, Select):
        return _plan_select(stmt, catalog, indexer)
    if isinstance(stmt, InsertStmt):
        return _plan_insert(stmt, catalog)
    if isinstance(stmt, UpdateStmt):
        return _plan_update(stmt, catalog)
    if isinstance(stmt, DeleteStmt):
        return _plan_delete(stmt, catalog)
    raise NotImplementedError(
        f"planner does not handle DDL statement: {type(stmt).__name__}"
    )


def _plan_select(
    stmt: Select,
    catalog: Catalog,
    indexer: Optional[IndexManager] = None,
) -> Plan:
    meta = _require_table(stmt.table, catalog)
    if stmt.where is not None:
        _validate_expr_columns(stmt.where, meta)

    # Source: SeqScan by default; IndexScan when _try_index_plan succeeds.
    src: Plan = SeqScan(table=meta.name)
    if stmt.where is not None:
        index_plan = _try_index_plan(stmt.where, meta, indexer)
        src = Filter(src=src, predicate=stmt.where)
        if index_plan is not None:
            src = Filter(src=index_plan, predicate=stmt.where)

    src = Project(
        src=src,
        columns=_project_columns(stmt, meta),
        items=tuple(stmt.columns),
    )

    # ORDER BY → Sort (sort-only plan, no limit/offset).
    if stmt.order_by:
        keys = [(ob.column, ob.descending) for ob in stmt.order_by]
        known = set(meta_column_names(meta))
        for col, _ in keys:
            if col not in known:
                raise UnknownColumnError(col)
        src = Sort(src=src, keys=keys)

    # LIMIT/OFFSET → dedicated Limit plan, wrapping any Sort.
    if stmt.limit is not None or stmt.offset:
        src = Limit(
            src=src,
            limit=stmt.limit if stmt.limit is not None else 0,
            offset=stmt.offset or 0,
        )

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
            out.append(type(item).__name__)
    return out


def _plan_insert(stmt: InsertStmt, catalog: Catalog) -> Plan:
    _require_table(stmt.table, catalog)
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
    # Literal / TypedLiteral / Star / Aggregate — nothing to validate.


def _try_index_plan(
    predicate: Optional[Expr],
    meta: TableMeta,
    indexer: Optional[IndexManager] = None,
) -> Optional[IndexScan]:
    """Pick an :class:`IndexScan` if a single-column predicate matches.

    Walks the WHERE clause via :func:`extract_indexable`.  When the
    resulting :class:`IndexablePredicate` names a column covered by a
    live index, returns the corresponding :class:`IndexScan`; otherwise
    ``None`` so the caller falls back to ``SeqScan + Filter``.
    """
    cols = tuple(c.name for c in meta.columns)
    pred = extract_indexable(predicate, cols)
    if pred is None or indexer is None:
        return None
    idx_meta = _find_index_for_column(meta, pred.column, indexer)
    if idx_meta is None:
        return None
    if pred.hi_op is None:
        if pred.op == "=":
            return IndexScan(
                table=meta.name, index=idx_meta.name,
                lo=pred.value, hi=pred.value,
                lo_inclusive=True, hi_inclusive=True,
            )
        return IndexScan(
            table=meta.name, index=idx_meta.name,
            lo=pred.value, hi=None,
            lo_inclusive=pred.op in ("=", ">=", "<="),
            hi_inclusive=True,
        )
    return IndexScan(
        table=meta.name, index=idx_meta.name,
        lo=pred.value, hi=pred.hi_value,
        lo_inclusive=pred.op in ("=", ">=", "<="),
        hi_inclusive=pred.hi_op in ("=", "<=", ">="),
    )


def _find_index_for_column(
    meta: TableMeta, column: str, indexer: IndexManager
) -> Optional[IndexMeta]:
    """Return the first single-column index covering ``column``."""
    for idx_meta in indexer._meta_by_name.values():
        if idx_meta.table == meta.name and idx_meta.columns == (column,):
            return idx_meta
    return None


__all__ = ["Executor", "plan", "UnknownTableError", "UnknownColumnError"]
