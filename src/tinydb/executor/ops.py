"""Plan tree dataclasses — AST → execution-plan translation layer.

Each :class:`Plan` subclass is a frozen, slotted dataclass carrying the
opaque fields a downstream executor needs to materialize rows.
T-5.1 fixes the tree shape; T-5.2..5.6 implement ``open`` to turn
plans into :class:`Row` streams.

Every Plan is ``@dataclass(frozen=True, slots=True)`` so two identical
plan trees are interchangeable and the executor can cache / hash them
freely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator, Optional, Sequence

if TYPE_CHECKING:
    from tinydb.executor.planner import Executor, UnknownColumnError


Row = tuple


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    """Marker base — concrete plans are subclasses below.

    ``op_name`` is a class-level discriminator so debug logs can switch
    on a single string field.
    """

    op_name: str = "Plan"

    def open(self, ctx: "Executor") -> Iterator[Row]:  # noqa: F821
        raise NotImplementedError("T-5.2 will implement actual execution")

    def __iter__(self) -> Iterator[Row]:  # pragma: no cover
        return self.open(None)  # type: ignore[arg-type]

    @property
    def table(self) -> str:
        """The base table this plan reads/writes.

        Wrappers traverse to the leaf; leaf plans override to return
        their own ``table`` attribute.
        """
        raise NotImplementedError(
            f"table property not implemented for {type(self).__name__}"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SeqScan(Plan):
    """Scan every row of ``table`` in heap order."""

    table: str
    op_name: str = "SeqScan"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.__dict__["table"]

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.executor.row_iter import TableScan

        meta = ctx.catalog.get_table(self.table)
        heap = ctx.heap_for(meta)
        for _rid, row in TableScan(heap, meta):
            yield row


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexScan(Plan):
    """Range scan over a single-column index.

    ``lo`` / ``hi`` are ``None`` for open-ended bounds; ``lo_inclusive``
    / ``hi_inclusive`` mirror SQL's ``[)`` semantics for ordered ranges.
    """

    table: str
    index: str
    lo: Any = None
    hi: Any = None
    lo_inclusive: bool = True
    hi_inclusive: bool = True
    op_name: str = "IndexScan"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.__dict__["table"]

    def open(self, ctx: "Executor") -> Iterator[Row]:
        """Yield decoded row tuples for each rid in the index range."""
        from tinydb.executor.index_scan import IndexLookup
        from tinydb.types.codec import decode_row

        idx_obj = ctx.indexer_for(self.table, self.index) if ctx.indexer else None
        if idx_obj is None:
            return  # defensive; planner should never pick IndexScan w/o indexer
        meta = ctx.catalog.get_table(self.table)
        tags = tuple(c.tag for c in meta.columns)
        heap = ctx.heap_for(meta)
        lookup = IndexLookup(ctx.indexer, idx_obj, tags[0])
        is_equality = (
            self.lo is not None
            and self.hi is not None
            and self.lo == self.hi
            and self.lo_inclusive
            and self.hi_inclusive
        )
        if is_equality:
            rids = lookup.equality(self.lo)
        else:
            rids = lookup.range(
                self.lo, self.hi,
                lo_inclusive=self.lo_inclusive,
                hi_inclusive=self.hi_inclusive,
            )
        for rid, _key in rids:
            blob = heap.read(rid)
            if blob is None:
                continue
            yield decode_row(blob, tags)


@dataclass(frozen=True, slots=True, kw_only=True)
class Filter(Plan):
    """Filter ``src`` rows using a predicate (an :class:`Expr` AST node)."""

    src: Plan
    predicate: object  # Expr from tinydb.sql.ast
    op_name: str = "Filter"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.src.table

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.executor.eval_expr import eval_expr

        n2i = ctx.name_to_idx_for(self.table)
        for row in self.src.open(ctx):
            v = eval_expr(self.predicate, row, n2i)  # type: ignore[arg-type]
            if v:
                yield row


@dataclass(frozen=True, slots=True, kw_only=True)
class Project(Plan):
    """Project ``src`` rows onto the declared ``columns``.

    For ``SELECT *`` the planner produces a Project listing every
    column of the table in declared order (so the executor sees a
    uniform shape regardless of the SQL form).  ``items`` is the
    parallel AST list so non-trivial projections (``SELECT 1+2``)
    can be evaluated; aggregates (T-5.6) raise.
    """

    src: Plan
    columns: Sequence[str]
    items: Sequence[object] = ()  # Expr nodes parallel to ``columns``
    op_name: str = "Project"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.src.table

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.executor.eval_expr import eval_expr

        n2i = ctx.name_to_idx_for(self.table)
        for row in self.src.open(ctx):
            out: list = []
            for i, col_name in enumerate(self.columns):
                if col_name in n2i:
                    out.append(row[n2i[col_name]])
                elif self.items and i < len(self.items):
                    out.append(eval_expr(self.items[i], row, n2i))  # type: ignore[arg-type]
                else:
                    raise NotImplementedError(
                        f"project column {col_name!r} has no source item"
                    )
            yield tuple(out)


@dataclass(frozen=True, slots=True, kw_only=True)
class Sort(Plan):
    """In-memory sort of ``src`` rows by ``keys``.

    ``keys`` is a sequence of ``(column, descending)`` tuples.  An empty
    sequence is identity (no sort).  T-5.4 split the previous
    ``Limit = Sort`` alias into a dedicated :class:`Limit` plan.
    """

    src: Plan
    keys: Sequence[tuple]  # (column, descending: bool)
    op_name: str = "Sort"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.src.table

    def open(self, ctx: "Executor") -> Iterator[Row]:
        from tinydb.executor.planner import UnknownColumnError

        rows = list(self.src.open(ctx))
        if not self.keys:
            yield from rows
            return
        col_idx = ctx.name_to_idx_for(self.table)
        for col, _ in self.keys:
            if col not in col_idx:
                raise UnknownColumnError(f"{self.table}.{col}")
        rows.sort(key=_sort_key(col_idx, self.keys))
        yield from rows


@dataclass(frozen=True, slots=True, kw_only=True)
class Limit(Plan):
    """Slice ``src``: skip ``offset`` rows, then yield at most ``limit``.

    Negative ``limit`` or ``offset`` raises :class:`ValueError`.
    ``limit`` larger than rowcount returns whatever is left (no
    padding).  T-5.4 split this from :class:`Sort`.
    """

    src: Plan
    limit: int
    offset: int = 0
    op_name: str = "Limit"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.src.table

    def open(self, ctx: "Executor") -> Iterator[Row]:
        if self.limit < 0:
            raise ValueError("LIMIT must be non-negative")
        if self.offset < 0:
            raise ValueError("OFFSET must be non-negative")
        rows = list(self.src.open(ctx))
        yield from rows[self.offset : self.offset + self.limit]


def _neg(value: Any) -> Any:
    """Negate a comparable for DESC sort.  None is filtered upstream."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return -value
    raise TypeError(f"DESC sort: cannot negate {type(value).__name__}")


def _sort_key(col_idx: dict, keys: Sequence[tuple]):
    """Sort-key encoder honouring NULL ordering (SQLite default).

    Each tuple element is ``(is_null, value_or_neg)`` so NULLs sort
    last in ASC (encoded as ``(1, 0)``) and first in DESC
    (encoded as ``(0, 0)``).
    """
    def encode(row: Row) -> tuple:
        parts = []
        for col, desc in keys:
            v = row[col_idx[col]]
            if v is None:
                parts.append((0, 0) if desc else (1, 0))
            else:
                parts.append((1, _neg(v)) if desc else (0, v))
        return tuple(parts)
    return encode


@dataclass(frozen=True, slots=True, kw_only=True)
class Insert(Plan):
    """Insert one row into ``table``."""

    table: str
    values: tuple
    op_name: str = "Insert"


@dataclass(frozen=True, slots=True, kw_only=True)
class Update(Plan):
    """Update rows of ``table`` selected by ``predicate`` (``None`` = all)."""

    table: str
    assignments: Sequence[tuple]  # (column, Expr)
    predicate: object  # Expr | None
    op_name: str = "Update"


@dataclass(frozen=True, slots=True, kw_only=True)
class Delete(Plan):
    """Delete rows of ``table`` selected by ``predicate`` (``None`` = all)."""

    table: str
    predicate: object  # Expr | None
    op_name: str = "Delete"


__all__ = [
    "Plan",
    "Row",
    "SeqScan",
    "IndexScan",
    "Filter",
    "Project",
    "Sort",
    "Limit",
    "Insert",
    "Update",
    "Delete",
]