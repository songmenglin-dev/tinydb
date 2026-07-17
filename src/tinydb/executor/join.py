"""JOIN execution — NestedLoopJoin and IndexedNestedLoopJoin operators.

REQ coverage
------------
* REQ-JOIN-6 — NestedLoopJoin for INNER + LEFT, NULL-padding on LEFT.
* REQ-JOIN-7 — IndexedNestedLoopJoin when inner-side has a B-tree
  index on the join key.

Design
------
Both operators share the same row-shape contract: each output row is
``(left_row..., right_row...)`` — left table's columns followed by
right table's columns.  The downstream :class:`Project` (T-12.5) reads
the result via the executor's per-table name_to_idx helpers, which
knows how to project an aliased SELECT.

LEFT JOIN handling: when no right row matches, yield ``(left_row...,
NULL, NULL, ..., NULL)`` — one NULL per right-table column.  This keeps
the row layout uniform so downstream stages don't need a flag column.

Key resolution
--------------
The on_expr is an :class:`Expr` evaluated against a "joined" row
whose :func:`eval_expr` is given a merged ``name_to_idx`` covering
both sides.  This is built by :func:`merge_n2i` so column refs like
``u.id`` find the right slot regardless of side.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional, Sequence

from tinydb.executor.eval_expr import eval_expr
from tinydb.executor.index_scan import IndexLookup
from tinydb.executor.logical import JoinNode, LogicalPlan, TableRef_
from tinydb.executor.ops import Plan
from tinydb.index.manager import IndexManager
from tinydb.sql.ast import BinaryOp, ColumnRef, Expr
from tinydb.storage.catalog import Catalog


def merge_n2i(left_n2i: dict, right_n2i: dict, alias_left: Optional[str],
              alias_right: Optional[str]) -> dict:
    """Build a merged ``{column_or_alias_col: position}`` map.

    Joins ``left_n2i`` (positions ``0..len(left_n2i)-1``) with
    ``right_n2i`` (positions shifted by ``len(left_n2i)``).  Also
    adds ``{alias}.col`` entries so qualified refs resolve to the
    correct slot when both tables share column names.

    Bare-name precedence: when a column name exists in BOTH sides the
    LEFT side wins, so unqualified references (``id``) see the driving
    table.  Callers that need the right side must use the qualified
    form (``o.id``) — that's also how the SQL query exposes them.
    """
    out: dict = {}
    left_size = len(left_n2i)
    for col, idx in left_n2i.items():
        out[col] = idx
        if alias_left is not None:
            out[f"{alias_left}.{col}"] = idx
    for col, idx in right_n2i.items():
        shifted = idx + left_size
        if col not in out:
            # LEFT wins on bare-name collisions so projections can
            # keep emitting unqualified columns for the outer table.
            out[col] = shifted
        if alias_right is not None:
            out[f"{alias_right}.{col}"] = shifted
    return out


def row_n2i_for_plan(plan, ctx, alias: Optional[str] = None) -> dict:
    """Build the recursive ``{col_or_alias_col: row_position}`` for any plan.

    Walks the Plan tree; for a leaf :class:`SeqScan` /
    :class:`IndexScan` returns that table's ``name_to_idx`` plus any
    ``{alias}.{col}`` entries when an alias is supplied.  For a Join it
    recursively merges the left and right row layouts, shifting the
    right side by ``max(left positions) + 1`` — the true physical width
    of the left subtree — so each side's local column position lands
    at its actual row slot.

    The earlier ``max(bare positions) + 1`` formula undercounted when a
    nested join's inner-table trailing column collided with an outer
    column: the collision was recorded only as a qualified
    ``alias.col`` key, leaving the bare set short by one position and
    the outer right side then landing on an overlapping slot.

    Other wrappers (:class:`Filter`, :class:`Project`, :class:`Sort`,
    :class:`Limit`) are unwrapped until a leaf or join is reached.  A
    bare-name collision keeps the left value (mirrors
    :func:`merge_n2i`'s precedence); qualified ``{alias}.{col}``
    entries are always added so the executor can disambiguate.

    Used by :class:`~tinydb.executor.ops.Project`, :class:`Filter`,
    and :class:`Sort` when their source is a join tree — the single-
    level :func:`merge_n2i` only walks one join at a time.
    """
    from tinydb.executor.ops import SeqScan, IndexScan
    if isinstance(plan, (SeqScan, IndexScan)):
        meta = ctx.catalog.get_table(plan.table)
        out: dict = {c.name: i for i, c in enumerate(meta.columns)}
        if alias is not None:
            for i, c in enumerate(meta.columns):
                out[f"{alias}.{c.name}"] = i
        return out
    if isinstance(plan, (NestedLoopJoin, IndexedNestedLoopJoin)):
        left_n2i = row_n2i_for_plan(plan.left, ctx, alias=plan.alias_left)
        right_n2i = row_n2i_for_plan(plan.right, ctx, alias=plan.alias_right)
        # Physical width of the left subtree = max position + 1,
        # counting BOTH bare and qualified entries.  Qualified entries
        # always sit at their bare position (or extend past it when
        # the bare was shadowed by a left-side winner), so taking the
        # max over all keys gives the true width without missing
        # collision-induced extensions.
        offset = (max(left_n2i.values()) + 1) if left_n2i else 0
        out = dict(left_n2i)
        for col, idx in right_n2i.items():
            shifted = idx + offset
            if "." in col:
                out[col] = shifted
            elif col not in out:
                out[col] = shifted
        return out
    if hasattr(plan, "src"):
        return row_n2i_for_plan(plan.src, ctx, alias=alias)
    return ctx.name_to_idx_for(getattr(plan, "table", ""))


def _right_row_with_nulls(right_n2i: dict, right_size: int) -> tuple:
    """Produce a right-sized NULL row for LEFT-JOIN padding."""
    return tuple(None for _ in range(right_size))


class NestedLoopJoin(Plan):
    """Left-driven nested-loop join (REQ-JOIN-6).

    For each left row, scan the entire right side; on match (or no
    match for LEFT JOIN) emit the combined row.  Streams lazily so
    we don't materialise either side up-front.
    """

    def __init__(
        self,
        left: Plan,
        right: Plan,
        on_expr: Optional[Expr],
        kind: str,
        *,
        nullable_right: bool = False,
        alias_left: Optional[str] = None,
        alias_right: Optional[str] = None,
        right_columns: Sequence[str] = (),
    ) -> None:
        # Plan's frozen-dataclass machinery uses kwargs; bypass by
        # calling object.__setattr__ in the dataclass-friendly way.
        object.__setattr__(self, "left", left)
        object.__setattr__(self, "right", right)
        object.__setattr__(self, "on_expr", on_expr)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "nullable_right", nullable_right)
        object.__setattr__(self, "alias_left", alias_left)
        object.__setattr__(self, "alias_right", alias_right)
        object.__setattr__(self, "right_columns", tuple(right_columns))
        object.__setattr__(self, "op_name", "NestedLoopJoin")

    @property
    def table(self) -> str:
        return self.left.table

    def open(self, ctx) -> Iterator[tuple]:
        # T-12.5: use the recursive helper so the on_expr sees columns
        # from NESTED joins on either side.  The legacy merge_n2i only
        # walked two leaves; the helper walks the full subtree.
        merged_n2i = row_n2i_for_plan(self, ctx)
        right_n2i_local = ctx.name_to_idx_for(self.right.table)
        right_size = len(right_n2i_local)
        # Materialise right rows once so the LEFT loop doesn't
        # re-scan them for each outer row (v0.1 SeqScan is a generator
        # that re-reads on every call).
        right_rows = list(self.right.open(ctx))
        for left_row in self.left.open(ctx):
            matched = False
            for right_row in right_rows:
                if self.on_expr is None:
                    yield left_row + right_row
                    matched = True
                    continue
                combined = left_row + right_row
                ok = eval_expr(self.on_expr, combined, merged_n2i)
                if ok:
                    yield combined
                    matched = True
            if not matched and self.nullable_right:
                yield left_row + _right_row_with_nulls(right_n2i_local, right_size)


class IndexedNestedLoopJoin(Plan):
    """Index-driven nested-loop join (REQ-JOIN-7).

    Outer loop is the left (smaller / driving) side; the right side
    is probed via a B-tree equality lookup keyed on the left row's
    join column.  Streams lazily; only matching rows are produced.
    """

    def __init__(
        self,
        left: Plan,
        right: Plan,
        on_expr: Optional[Expr],
        kind: str,
        *,
        alias_left: Optional[str] = None,
        alias_right: Optional[str] = None,
        right_columns: Sequence[str] = (),
        right_table: str = "",
        right_index: str = "",
        right_key_column: str = "",
        left_key_alias: Optional[str] = None,
    ) -> None:
        object.__setattr__(self, "left", left)
        object.__setattr__(self, "right", right)
        object.__setattr__(self, "on_expr", on_expr)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "alias_left", alias_left)
        object.__setattr__(self, "alias_right", alias_right)
        object.__setattr__(self, "right_columns", tuple(right_columns))
        object.__setattr__(self, "right_table", right_table)
        object.__setattr__(self, "right_index", right_index)
        object.__setattr__(self, "right_key_column", right_key_column)
        object.__setattr__(self, "left_key_alias", left_key_alias)
        object.__setattr__(self, "op_name", "IndexedNestedLoopJoin")

    @property
    def table(self) -> str:
        return self.left.table

    def open(self, ctx) -> Iterator[tuple]:
        right_n2i = ctx.name_to_idx_for(self.right.table)
        right_size = len(right_n2i)
        if ctx.indexer is None:
            return
        idx_obj = ctx.indexer.get_by_name(self.right_index)
        if idx_obj is None:
            return
        right_meta = ctx.catalog.get_table(self.right_table)
        key_tag = right_meta.columns[
            [c.name for c in right_meta.columns].index(self.right_key_column)
        ].tag
        lookup = IndexLookup(ctx.indexer, idx_obj, key_tag)
        # When the driving (left) side is itself a JOIN (nested case),
        # ``ctx.name_to_idx_for(left.table)`` only sees the leftmost
        # leaf's columns and is therefore too narrow to resolve keys
        # on a non-leftmost leaf (``b.aid`` for ``a JOIN b``).  Use the
        # recursive ``row_n2i_for_plan`` so key extraction and ON
        # evaluation work against the full nested layout.
        full_left_n2i = row_n2i_for_plan(self.left, ctx, alias=self.left_key_alias)
        merged_n2i = row_n2i_for_plan(self, ctx)
        left_key_idx, right_key_idx = _extract_join_keys_nested(
            self.on_expr, full_left_n2i, right_n2i,
            self.left_key_alias, self.alias_right,
        )
        if left_key_idx is None or right_key_idx is None:
            return
        for left_row in self.left.open(ctx):
            key = left_row[left_key_idx]
            if key is None:
                if self.kind == "LEFT":
                    yield left_row + _right_row_with_nulls(right_n2i, right_size)
                continue
            matched_any = False
            for _rid, _key in lookup.equality(key):
                right_row = _fetch_row(ctx, self.right_table, _rid, right_n2i, right_meta)
                if right_row is None:
                    continue
                combined = left_row + right_row
                if self.on_expr is None or eval_expr(self.on_expr, combined, merged_n2i):
                    yield combined
                    matched_any = True
            if not matched_any and self.kind == "LEFT":
                yield left_row + _right_row_with_nulls(right_n2i, right_size)


def _fetch_row(ctx, table: str, rid, right_n2i: dict, right_meta) -> Optional[tuple]:
    """Decode a heap row from ``rid`` into a tuple aligned to ``right_n2i``."""
    from tinydb.types.codec import decode_row
    heap = ctx.heap_for(right_meta)
    blob = heap.read(rid)
    if blob is None:
        return None
    tags = tuple(c.tag for c in right_meta.columns)
    return decode_row(blob, tags)


def _extract_join_keys(
    on_expr: Optional[Expr],
    left_n2i: dict,
    right_n2i: dict,
    alias_left: Optional[str],
    alias_right: Optional[str],
) -> tuple:
    """Find left + right column indices from ``on_expr``.

    Returns ``(left_idx, right_idx)`` for the simple equality
    ``left.col = right.col`` case.  Returns ``(None, None)`` for any
    other shape (composite / OR / range / etc.) so the caller falls
    back to NLJ.

    Both ``left_n2i`` and ``right_n2i`` are expected to be plain
    ``{column_name: position}`` maps for SINGLE-TABLE sides.  Callers
    with a nested left side (a JOIN) must use
    :func:`_extract_join_keys_nested` so the driving row's full width
    is used for the left index.
    """
    if not isinstance(on_expr, BinaryOp) or on_expr.op != "=":
        return (None, None)
    left_ref = on_expr.left
    right_ref = on_expr.right
    if not isinstance(left_ref, ColumnRef) or not isinstance(right_ref, ColumnRef):
        return (None, None)
    # Determine which side each ref belongs to.
    def _side_idx(ref: ColumnRef) -> Optional[int]:
        if ref.table is None:
            # Bare ref — assume left if it lives there, else right.
            if ref.name in left_n2i:
                return left_n2i[ref.name]
            if ref.name in right_n2i:
                # Shift by left size to land in the combined tuple.
                return right_n2i[ref.name] + len(left_n2i)
            return None
        if alias_left and ref.table == alias_left:
            if ref.name in left_n2i:
                return left_n2i[ref.name]
            return None
        if alias_right and ref.table == alias_right:
            if ref.name in right_n2i:
                return right_n2i[ref.name] + len(left_n2i)
            return None
        return None
    l = _side_idx(left_ref)
    r = _side_idx(right_ref)
    if l is None or r is None:
        return (None, None)
    return (l, r)


def _extract_join_keys_nested(
    on_expr: Optional[Expr],
    full_left_n2i: dict,
    right_n2i: dict,
    alias_left: Optional[str],
    alias_right: Optional[str],
) -> tuple:
    """Like :func:`_extract_join_keys` but for a nested driving side.

    ``full_left_n2i`` is the recursive map returned by
    :func:`row_n2i_for_plan` on the LEFT subplan; it carries every
    bare and qualified column position across the LEFT's nested
    layout.  The right key index is shifted by ``len(full_left_n2i)``
    because nested INLJs only emit a single combined ``combined =
    left_row + right_row`` at the parent level — but for the index
    lookup we want ``left_row``-local positions on the left side and
    RIGHT-leaf-local positions on the right side; the shift puts the
    right index in terms of the COMBINED row, which is where
    :func:`eval_expr` will read it.
    """
    if not isinstance(on_expr, BinaryOp) or on_expr.op != "=":
        return (None, None)
    left_ref = on_expr.left
    right_ref = on_expr.right
    if not isinstance(left_ref, ColumnRef) or not isinstance(right_ref, ColumnRef):
        return (None, None)

    def _left_idx(ref: ColumnRef) -> Optional[int]:
        # Try the qualified form first (works whether the driving side
        # is a leaf or a nested join); then fall back to the bare name.
        if ref.table is not None:
            key = f"{ref.table}.{ref.name}"
            if key in full_left_n2i:
                return full_left_n2i[key]
        return full_left_n2i.get(ref.name)

    def _right_idx(ref: ColumnRef) -> Optional[int]:
        if ref.table is not None and ref.table == alias_right:
            return right_n2i[ref.name] + len(full_left_n2i)
        # Bare name — only safe when unambiguous on the right side.
        if ref.name in right_n2i:
            return right_n2i[ref.name] + len(full_left_n2i)
        return None

    l = _left_idx(left_ref)
    r = _right_idx(right_ref)
    if l is None or r is None:
        return (None, None)
    return (l, r)


__all__ = [
    "IndexedNestedLoopJoin",
    "NestedLoopJoin",
    "merge_n2i",
    "row_n2i_for_plan",
]