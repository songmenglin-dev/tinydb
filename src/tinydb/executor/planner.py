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

T-12.1 split
------------
:class:`LogicalPlanner` (B11) and :class:`PhysicalPlanner` are
introduced as thin class-based entry points so callers can pass
``(catalog, index_manager)`` once at construction and plan multiple
queries without re-injecting dependencies.  Both classes delegate to
the existing function-shaped helpers so v0.1 tests keep working
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, TYPE_CHECKING

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

if TYPE_CHECKING:  # pragma: no cover — only for type checkers
    from tinydb.executor.logical import LogicalPlan


class UnknownTableError(TinydbError):
    """A statement referenced a table that is not in the catalog."""


class UnknownColumnError(TinydbError):
    """A statement referenced a column that does not exist in the table."""


# --- T-12.1: PhysicalPlanner / PhysicalPlan / PhysicalNode ------------


class PhysicalNode:
    """Marker — every physical-plan tree node inherits from this class.

    The tree itself is the existing ``tinydb.executor.ops.Plan``
    hierarchy (SeqScan / IndexScan / Filter / Project / Sort / Limit /
    NestedLoopJoin / IndexedNestedLoopJoin).  :class:`PhysicalNode` is a
    sibling marker so the new :class:`PhysicalPlan` container can accept
    any of them without re-exporting v0.1 ``Plan`` here.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class PhysicalPlan:
    """Top-level physical plan: an ordered list of root nodes.

    v0.2 only emits a single root node per SELECT, so ``steps`` carries
    one entry; the list shape is preserved to make room for parallel /
    multi-step plans in later batches (Batch 16+).
    """

    steps: List["Plan | PhysicalNode"] = field(default_factory=list)


class PhysicalPlanner:
    """LogicalPlan → PhysicalPlan with catalog + index_manager injection.

    The planner is stateful only in (catalog, index_manager); ``plan``
    builds a fresh :class:`PhysicalPlan` on each call.  Selection rules
    mirror the legacy :func:`emit_physical` (NLJ fallback, INLJ when
    the inner-side join column has a live index).
    """

    def __init__(
        self,
        catalog: Catalog,
        index_manager: Optional[IndexManager] = None,
    ) -> None:
        self._catalog = catalog
        self._index_manager = index_manager

    @property
    def catalog(self) -> Catalog:
        """Read-only handle to the injected catalog."""
        return self._catalog

    @property
    def index_manager(self) -> Optional[IndexManager]:
        """Read-only handle to the injected IndexManager (may be None)."""
        return self._index_manager

    def plan(self, logical: "LogicalPlan") -> PhysicalPlan:
        """Lower ``logical`` into a :class:`PhysicalPlan` tree.

        Dispatches into the legacy free-function
        :func:`tinydb.executor.physical.emit_physical` so any operator
        selection tweak lands in one place.  Returns a single-step
        :class:`PhysicalPlan` wrapping the produced :class:`Plan`.
        """
        from tinydb.executor.physical import emit_physical
        tree = emit_physical(logical, self._catalog, self._index_manager)
        return PhysicalPlan(steps=[tree])


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
    # T-11/12 split: route through LogicalPlanner → PhysicalPlanner.
    # The legacy code below remains for any direct callers that build
    # a Select without a from_ clause; in practice every parsed SELECT
    # has a from_ and the new path runs.
    from tinydb.sql.ast import Table as AstTable
    if isinstance(stmt.from_, AstTable):
        # Single-table fast path — same shape as v0.1.
        meta = _require_table(stmt.from_.name, catalog)
        if stmt.where is not None:
            _validate_expr_columns(stmt.where, meta)

        # Source: SeqScan by default; IndexScan when _try_index_plan succeeds.
        src: Plan = SeqScan(table=meta.name)
        if stmt.where is not None:
            index_plan = _try_index_plan(stmt.where, meta, indexer)
            src = Filter(src=src, predicate=stmt.where)
            if index_plan is not None:
                src = Filter(src=index_plan, predicate=stmt.where)

        agg_pairs: tuple = tuple(
            (c.func, c.column) for c in stmt.columns if isinstance(c, Aggregate)
        )
        if agg_pairs or stmt.group_by:
            from tinydb.executor.aggregate import Aggregate as AggregatePlan

            src = AggregatePlan(
                src=src,
                aggregates=agg_pairs,
                keys=tuple(stmt.group_by),
            )
        else:
            src = Project(
                src=src,
                columns=_project_columns(stmt, meta),
                items=tuple(stmt.columns),
            )

        if stmt.order_by:
            keys = [(ob.column, ob.descending) for ob in stmt.order_by]
            known = set(meta_column_names(meta))
            for col, _ in keys:
                if col not in known:
                    raise UnknownColumnError(col)
            src = Sort(src=src, keys=keys)

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

    # JOIN path: emit logical, run through the new class-based
    # PhysicalPlanner (T-12.6), then wrap with WHERE/Project/Sort/Limit.
    from tinydb.executor.logical import emit_logical
    from tinydb.executor.physical import _wrap_with_select_clauses as _wrap
    # T-13.1: pass the catalog so emit_logical can build a real
    # column → owner map and only flag bare columns that genuinely
    # exist in multiple joined tables (REQ-JOIN-8).
    logical = emit_logical(stmt, catalog=catalog)
    phys_planner = PhysicalPlanner(catalog, indexer)
    physical = phys_planner.plan(logical)
    # ``PhysicalPlan.steps`` carries the root node; v0.2 SELECTs only
    # produce a single step.  Unwrap for ``_wrap`` to add the SELECT-
    # trailing clauses around the JOIN tree.
    base = physical.steps[0]
    return _wrap(base, stmt, catalog)


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
    meta = _require_table(stmt.table, catalog)
    # If the user supplied an explicit column list, expand each VALUES
    # row into the table's full column order, substituting NULL for
    # any column not named in the list.  T-7.2 closes the gap between
    # the parser (which already supports ``INSERT INTO t (a, c)``) and
    # the executor (which only accepted full-width rows).
    if stmt.columns is None:
        expanded = stmt.values
    else:
        col_names = [c.name for c in meta.columns]
        for name in stmt.columns:
            if name not in col_names:
                raise UnknownColumnError(
                    f"{stmt.table!r}.{name!r}"
                )
        idx_map = [col_names.index(c) for c in stmt.columns]
        expanded = []
        for row in stmt.values:
            if len(row) != len(stmt.columns):
                raise ValueError(
                    f"INSERT into {stmt.table!r}: "
                    f"{len(stmt.columns)} columns named but "
                    f"{len(row)} values supplied"
                )
            full = [None] * len(col_names)
            for i, val in zip(idx_map, row):
                full[i] = val
            expanded.append(tuple(full))
    return InsertPlan(table=stmt.table, values=tuple(expanded))


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
