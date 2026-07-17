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
        left_n2i = ctx.name_to_idx_for(self.left.table)
        right_n2i = ctx.name_to_idx_for(self.right.table)
        right_size = len(right_n2i)
        for left_row in self.left.open(ctx):
            matched = False
            merged_n2i = merge_n2i(
                left_n2i, right_n2i, self.alias_left, self.alias_right,
            )
            for right_row in self.right.open(ctx):
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
                yield left_row + _right_row_with_nulls(right_n2i, right_size)


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
        left_n2i = ctx.name_to_idx_for(self.left.table)
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
        left_key_idx, right_key_idx = _extract_join_keys(
            self.on_expr, left_n2i, right_n2i,
            self.alias_left, self.alias_right,
        )
        if left_key_idx is None or right_key_idx is None:
            return
        merged_n2i = merge_n2i(
            left_n2i, right_n2i, self.alias_left, self.alias_right,
        )
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


__all__ = [
    "IndexedNestedLoopJoin",
    "NestedLoopJoin",
    "merge_n2i",
]