"""Physical planner — LogicalPlan → Plan tree, with JOIN operator selection.

REQ coverage
------------
* REQ-JOIN-6  — emits :class:`NestedLoopJoin` for JOIN nodes.
* REQ-JOIN-7  — picks :class:`IndexedNestedLoopJoin` when an index
  covers the inner-side join column AND the equality is simple.
* REQ-JOIN-9  — WHERE is applied AFTER the JOIN: the WHERE filter is
  wrapped on the Join plan, not inserted between scans.
* REQ-JOIN-10 — single-table SELECTs keep emitting SeqScan/IndexScan
  exactly as in v0.1.

Split out of :mod:`tinydb.executor.planner` in T-12.1; the planner
becomes a thin entry point that calls ``emit_logical`` then
``emit_physical``.  Single-table WHERE/project/sort/limit wrapping
still lives in :mod:`tinydb.executor.planner` so this module only
deals with the JOIN-aware projection (deduplicating USING columns,
walking all FROM tables for WHERE validation, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from tinydb.executor.join import (
    IndexedNestedLoopJoin,
    NestedLoopJoin,
)
from tinydb.executor.logical import JoinNode, TableRef_
from tinydb.executor.ops import (
    Filter,
    Limit as LimitPlan,
    Plan,
    Project,
    SeqScan,
    Sort as SortPlan,
)
from tinydb.executor.planner import (
    UnknownColumnError,
    _require_table,
    _walk_expr,
    meta_column_names,
)
from tinydb.index.manager import IndexManager
from tinydb.sql.ast import (
    Aggregate,
    BinaryOp,
    ColumnRef,
    Expr,
    Literal,
    Select,
    Star,
    TypedLiteral,
)
from tinydb.storage.catalog import Catalog


def emit_physical(
    logical,
    catalog: Catalog,
    indexer: Optional[IndexManager] = None,
) -> Plan:
    """Translate a :class:`LogicalPlan` into a :class:`Plan` tree.

    Dispatches on the logical node type:

    * :class:`TableRef_` → SeqScan (or IndexScan if WHERE matches)
    * :class:`JoinNode`  → NestedLoopJoin (or IndexedNestedLoopJoin when
      an index covers the inner-side key)
    """
    if isinstance(logical, TableRef_):
        return _emit_tableref(logical, catalog)
    if isinstance(logical, JoinNode):
        return _emit_join(logical, catalog, indexer)
    raise NotImplementedError(
        f"physical planner: unsupported logical node {type(logical).__name__}"
    )


def _emit_tableref(node: TableRef_, catalog: Catalog) -> Plan:
    meta = _require_table(node.table, catalog)
    return SeqScan(table=meta.name)


def _emit_join(
    node: JoinNode,
    catalog: Catalog,
    indexer: Optional[IndexManager],
) -> Plan:
    left = emit_physical(node.left, catalog, indexer)
    right = emit_physical(node.right, catalog, indexer)
    alias_left = _alias_for(node.left)
    alias_right = _alias_for(node.right)
    right_meta = _require_table(right.table, catalog)
    right_columns = list(meta_column_names(right_meta))
    # Try INLJ first (REQ-JOIN-7); fall back to NLJ when no index or
    # the on_expr is not a simple equality.
    if indexer is not None:
        idx_plan = _try_indexed_join(node, catalog, indexer, alias_left)
        if idx_plan is not None:
            return IndexedNestedLoopJoin(
                left=left,
                right=right,
                on_expr=node.on_expr,
                kind=node.kind,
                alias_left=alias_left,
                alias_right=alias_right,
                right_columns=right_columns,
                right_table=right_meta.name,
                right_index=idx_plan.index,
                right_key_column=idx_plan.key_column,
                left_key_alias=idx_plan.left_alias,
            )
    return NestedLoopJoin(
        left=left,
        right=right,
        on_expr=node.on_expr,
        kind=node.kind,
        nullable_right=node.nullable_right,
        alias_left=alias_left,
        alias_right=alias_right,
        right_columns=right_columns,
    )


def _alias_for(node) -> Optional[str]:
    if isinstance(node, TableRef_):
        # When the SQL doesn't alias a table, fall back to its bare
        # name so qualified refs like ``t1.id`` still resolve (the
        # alias map keys on the bare name when no alias is set).
        return node.alias or node.table
    return None


# --- INLJ selection ----------------------------------------------------


def _try_indexed_join(
    node: JoinNode,
    catalog: Catalog,
    indexer: IndexManager,
    alias_left: Optional[str],
) -> Optional["_IndexJoinPlan"]:
    """If the join is a single-column equality AND an index covers the
    right side's key column, return a small plan record.

    Returns ``None`` so the caller falls back to NestedLoopJoin.  Only
    equality predicates with both sides being :class:`ColumnRef` qualify
    — composite / OR / range predicates are too complex for v0.2.
    """
    on_expr = node.on_expr
    if not isinstance(on_expr, BinaryOp) or on_expr.op != "=":
        return None
    left_ref = on_expr.left
    right_ref = on_expr.right
    if not isinstance(left_ref, ColumnRef) or not isinstance(right_ref, ColumnRef):
        return None
    # Decide which side is right — by alias match (if any), else by
    # canonical table membership on the JoinNode.right.
    right_node = node.right
    if not isinstance(right_node, TableRef_):
        return None
    right_meta = _require_table(right_node.table, catalog)
    # Determine which ref refers to the right side.
    def _ref_belongs_to(ref: ColumnRef) -> bool:
        if ref.table is None:
            # Bare column — assume left side (will fall back to NLJ).
            return False
        if right_node.alias is not None and ref.table == right_node.alias:
            return True
        if ref.table == right_node.table:
            return True
        return False
    if _ref_belongs_to(right_ref):
        right_key_col = right_ref.name
        left_alias = (
            left_ref.table if left_ref.table is not None else alias_left
        )
    elif _ref_belongs_to(left_ref):
        right_key_col = left_ref.name
        left_alias = (
            right_ref.table if right_ref.table is not None else alias_left
        )
    else:
        return None
    # Find an index covering the right_key_col on the right table.
    for idx_meta in indexer._meta_by_name.values():
        if (
            idx_meta.table == right_meta.name
            and idx_meta.columns == (right_key_col,)
        ):
            return _IndexJoinPlan(
                index=idx_meta.name,
                key_column=right_key_col,
                left_alias=left_alias,
            )
    return None


@dataclass
class _IndexJoinPlan:  # noqa: F821
    index: str
    key_column: str
    left_alias: Optional[str]


# --- JOIN-aware WHERE / projection / ordering wrapping -----------------


def _wrap_with_select_clauses(
    src: Plan,
    stmt: Select,
    catalog: Catalog,
) -> Plan:
    """Apply WHERE → Aggregate → Project → Sort → Limit on top of a JOIN plan.

    All table-metas come from the FROM tree so we know each column's
    source table for projection dedup (REQ-JOIN-8).  T-13.1 extends
    the single-table behaviour to JOIN sources so aggregates over a
    joined stream (``SELECT COUNT(*) FROM users JOIN orders``) work
    the same way they do for a single table.
    """
    # Validate WHERE columns against every table in the FROM tree.
    if stmt.where is not None:
        _validate_join_where(stmt.where, stmt, catalog)
        src = Filter(src=src, predicate=stmt.where)
    # T-13.1: aggregates over a joined stream — wire the same
    # AggregatePlan the single-table path uses, so COUNT/SUM/AVG/
    # MIN/MAX and GROUP BY all work over JOIN results too.  When the
    # SELECT list carries aggregates the row layout changes to
    # ``(group_keys..., agg_values...)``, so the projection step that
    # follows must operate on the AggregatePlan output, not on the
    # Join's merged layout.
    agg_pairs: tuple = tuple(
        (c.func, c.column) for c in stmt.columns if isinstance(c, Aggregate)
    )
    if agg_pairs or stmt.group_by:
        from tinydb.executor.aggregate import Aggregate as AggregatePlan

        # GROUP BY keys may be unqualified (validator already
        # disambiguated single-table refs upstream).
        keys = tuple(stmt.group_by)
        # Validate that each GROUP BY column resolves somewhere in
        # the joined schema; UnknownColumnError otherwise.
        if keys:
            known: set = set()
            for table in _all_tables_in_from(stmt.from_):
                meta = _require_table(table, catalog)
                for c in meta_column_names(meta):
                    known.add(c)
            for col in keys:
                if col not in known:
                    raise UnknownColumnError(col)
        src = AggregatePlan(src=src, aggregates=agg_pairs, keys=keys)
        # After an aggregate the projection list is just the SELECT
        # items — no USING dedup is meaningful on the post-aggregate
        # layout because the aggregates change the row shape.
        proj_cols: list = []
        seen: set = set()
        for item in stmt.columns:
            if isinstance(item, Aggregate):
                label = f"{item.func}({item.column})"
                if label not in seen:
                    proj_cols.append(label)
                    seen.add(label)
            elif isinstance(item, ColumnRef):
                if item.name not in seen:
                    proj_cols.append(item.name)
                    seen.add(item.name)
            elif isinstance(item, Literal):
                label = f"L:{item.value!r}"
                if label not in seen:
                    proj_cols.append(label)
                    seen.add(label)
            elif isinstance(item, TypedLiteral):
                label = f"L[{item.tag.name}]:{item.value!r}"
                if label not in seen:
                    proj_cols.append(label)
                    seen.add(label)
            elif isinstance(item, Star):
                # Star over an aggregate: emit every aggregate label.
                for func, col in agg_pairs:
                    label = f"{func}({col})"
                    if label not in seen:
                        proj_cols.append(label)
                        seen.add(label)
            else:
                label = type(item).__name__
                if label not in seen:
                    proj_cols.append(label)
                    seen.add(label)
        # Project the aggregate output.
        if stmt.order_by:
            src = SortPlan(
                src=Project(src=src, columns=proj_cols, items=()),
                keys=[
                    (ob.column, ob.descending) for ob in stmt.order_by
                ],
            )
        else:
            src = Project(src=src, columns=proj_cols, items=())
    else:
        # Project with deduplicated USING columns.
        src = Project(
            src=src,
            columns=_join_projection_columns(stmt, catalog),
            items=tuple(stmt.columns),
        )
        # ORDER BY — columns may be unqualified if unambiguous.
        if stmt.order_by:
            keys = [(ob.column, ob.descending) for ob in stmt.order_by]
            src = SortPlan(src=src, keys=keys)
    if stmt.limit is not None or stmt.offset:
        src = LimitPlan(
            src=src,
            limit=stmt.limit if stmt.limit is not None else 0,
            offset=stmt.offset or 0,
        )
    return src


def _validate_join_where(expr: Expr, stmt: Select, catalog: Catalog) -> None:
    """Walk WHERE; raise UnknownColumnError on unknown refs."""
    known: set = set()
    for table in _all_tables_in_from(stmt.from_):
        meta = _require_table(table, catalog)
        for c in meta_column_names(meta):
            known.add(c)
    _walk_expr(expr, known)


def _all_tables_in_from(from_ref) -> list:
    from tinydb.sql.ast import Join as AstJoin, Table
    out: list = []
    def _v(n):
        if isinstance(n, Table):
            out.append(n.name)
        elif isinstance(n, AstJoin):
            _v(n.left)
            _v(n.right)
    _v(from_ref)
    return out


def _join_projection_columns(stmt: Select, catalog: Catalog) -> list:
    """Build the deduped column-name list for a JOIN's projection.

    For ``SELECT *`` on a JOIN with USING, deduplicate the USING
    columns.  For explicit ColumnRef items, return the names as-is
    (the executor looks them up via the merged name_to_idx).
    """
    out: list = []
    seen: set = set()
    using_cols: list = []
    _collect_using(stmt.from_, using_cols)
    if len(stmt.columns) == 1 and isinstance(stmt.columns[0], Star):
        # SELECT * — emit every column from every table in order,
        # skipping duplicates introduced by USING.
        for table in _all_tables_in_from(stmt.from_):
            meta = _require_table(table, catalog)
            for col in meta_column_names(meta):
                if col in using_cols and col in seen:
                    continue
                if col not in seen:
                    out.append(col)
                    seen.add(col)
        return out
    for item in stmt.columns:
        if isinstance(item, Star):
            for table in _all_tables_in_from(stmt.from_):
                meta = _require_table(table, catalog)
                for col in meta_column_names(meta):
                    if col not in seen:
                        out.append(col)
                        seen.add(col)
        elif isinstance(item, ColumnRef):
            if item.name not in seen:
                out.append(item.name)
                seen.add(item.name)
        elif isinstance(item, Aggregate):
            label = f"{item.func}({item.column})"
            if label not in seen:
                out.append(label)
                seen.add(label)
        elif isinstance(item, Literal):
            label = f"L:{item.value!r}"
            if label not in seen:
                out.append(label)
                seen.add(label)
        elif isinstance(item, TypedLiteral):
            label = f"L[{item.tag.name}]:{item.value!r}"
            if label not in seen:
                out.append(label)
                seen.add(label)
        else:
            label = type(item).__name__
            if label not in seen:
                out.append(label)
                seen.add(label)
    return out


def _collect_using(node, out: list) -> None:
    from tinydb.sql.ast import Join as AstJoin
    if isinstance(node, AstJoin) and node.using:
        for c in node.using:
            if c not in out:
                out.append(c)
        _collect_using(node.left, out)
        _collect_using(node.right, out)
    elif isinstance(node, AstJoin):
        _collect_using(node.left, out)
        _collect_using(node.right, out)


__all__ = ["emit_physical"]