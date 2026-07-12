"""DML plans: INSERT / UPDATE / DELETE with index maintenance.

Split out of :mod:`tinydb.executor.ops` (T-5.5) to keep ``ops.py`` under
its 380-line cap.  All three plans share the same skeleton:

1. Resolve ``meta`` / ``tags`` / ``name_idx`` / ``heap`` for the target
   table through :func:`_dml_context`.
2. Walk the heap's live rids (snapshotted via ``list(heap.scan())``
   because DELETE / UPDATE mutate the chain).
3. For UPDATE the row is rewritten as ``delete(rid) + insert(blob)`` —
   the Rid changes, so index entries under the old Rid must be
   removed and the new key added.

NULL values are special-cased: a Python ``None`` is encoded as a
single ``TypeTag.Null`` byte regardless of the column tag (see
:func:`encode_row_coerced`), so SQL NULLs round-trip uniformly
through the heap + SELECT pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Sequence

if TYPE_CHECKING:
    from tinydb.executor.planner import Executor


Row = tuple


def _assert_not_null(
    row: Sequence, columns: Sequence, n2i: dict, table: str
) -> None:
    """Raise :class:`NotNullViolation` if any NOT NULL column is None.

    Called by :class:`Insert` and :class:`Update` BEFORE the row is
    encoded so a NULL violation surfaces with the column name rather
    than as a confusing codec error.
    """
    from tinydb.errors import NotNullViolation

    for col in columns:
        if col.not_null and row[n2i[col.name]] is None:
            raise NotNullViolation(
                f"NOT NULL constraint violated: "
                f"{table!r}.{col.name} received NULL"
            )


def _dml_context(ctx: "Executor", table: str) -> tuple:
    """Return ``(meta, tags, n2i, heap)`` for a DML plan.

    Centralises the meta/tags/n2i/heap setup.  The Heap is bound
    through :func:`tinydb.executor.heap_bind.bind_heap` so we reuse
    the catalog's heap chain rather than allocating a fresh page
    (T-5.2 NIT-10).
    """
    from tinydb.executor.heap_bind import bind_heap

    meta = ctx.catalog.get_table(table)
    tags = tuple(c.tag for c in meta.columns)
    n2i = {c.name: i for i, c in enumerate(meta.columns)}
    heap = bind_heap(ctx.catalog, table)
    return meta, tags, n2i, heap


@dataclass(frozen=True, slots=True, kw_only=True)
class Insert:
    """Insert one row into ``table`` (mirrors :class:`Plan` shape)."""

    table: str
    values: tuple

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.types.codec import encode_row_coerced

        meta, tags, n2i, heap = _dml_context(ctx, self.table)
        affected = 0
        for row_values in self.values:
            row_list = list(row_values)
            if len(row_list) != len(meta.columns):
                raise ValueError(
                    f"INSERT into {self.table!r}: expected "
                    f"{len(meta.columns)} values, got {len(row_list)}"
                )
            _assert_not_null(row_list, meta.columns, n2i, self.table)
            rid = heap.insert(encode_row_coerced(row_list, tags))
            if ctx.indexer is not None:
                ctx.indexer.on_insert(self.table, rid, tuple(row_list))
            affected += 1
        yield (affected,)


@dataclass(frozen=True, slots=True, kw_only=True)
class Update:
    """Update rows of ``table`` selected by ``predicate`` (``None`` = all)."""

    table: str
    assignments: Sequence[tuple]  # (column, Expr)
    predicate: object  # Expr | None

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.executor.eval_expr import eval_expr
        from tinydb.executor.planner import UnknownColumnError
        from tinydb.types.codec import decode_row, encode_row_coerced

        meta, tags, n2i, heap = _dml_context(ctx, self.table)
        affected = 0
        # Snapshot Rids — UPDATE writes a new Rid (Heap has no in-place
        # update), so we cannot iterate the live scan() safely.
        for rid in list(heap.scan()):
            blob = heap.read(rid)
            if blob is None:
                continue
            old_row = decode_row(blob, tags)
            if self.predicate is not None and not eval_expr(
                self.predicate, old_row, n2i  # type: ignore[arg-type]
            ):
                continue
            new_row = list(old_row)
            for col, expr in self.assignments:
                if col not in n2i:
                    raise UnknownColumnError(f"{self.table!r}.{col!r}")
                # type: ignore[arg-type]
                new_row[n2i[col]] = eval_expr(expr, old_row, n2i)
            _assert_not_null(new_row, meta.columns, n2i, self.table)
            heap.delete(rid)
            new_rid = heap.insert(encode_row_coerced(new_row, tags))
            if ctx.indexer is not None:
                # Rid changes (delete + insert): drop the old index
                # entry, then add the new one.
                ctx.indexer.on_delete(self.table, rid, old_row)
                ctx.indexer.on_insert(self.table, new_rid, tuple(new_row))
            affected += 1
        yield (affected,)


@dataclass(frozen=True, slots=True, kw_only=True)
class Delete:
    """Delete rows of ``table`` selected by ``predicate`` (``None`` = all)."""

    table: str
    predicate: object  # Expr | None

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.executor.eval_expr import eval_expr
        from tinydb.types.codec import decode_row

        meta, tags, n2i, heap = _dml_context(ctx, self.table)
        affected = 0
        for rid in list(heap.scan()):
            blob = heap.read(rid)
            if blob is None:
                continue
            row = decode_row(blob, tags)
            if self.predicate is not None and not eval_expr(
                self.predicate, row, n2i  # type: ignore[arg-type]
            ):
                continue
            heap.delete(rid)
            if ctx.indexer is not None:
                ctx.indexer.on_delete(self.table, rid, row)
            affected += 1
        yield (affected,)


__all__ = ["Insert", "Update", "Delete"]