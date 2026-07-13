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

# DML plans live in :mod:`tinydb.executor.dml` (T-5.5 split).  They are
# re-exported below so ``from tinydb.executor.ops import Insert`` still
# works for the planner and any external callers.
from tinydb.executor.dml import Delete, Insert, Update  # noqa: E402,F401

# T-5.6: aggregate plan lives in its own module (kept out of ops to
# keep this module under its line cap and let the aggregate helpers
# stay self-contained).  It imports :class:`Plan` from this module,
# so a top-level import would be circular — register a lazy
# __getattr__ that resolves ``Aggregate`` on first access.


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
        from tinydb.executor.aggregate import Aggregate as AggregatePlan
        from tinydb.executor.planner import UnknownColumnError

        rows = list(self.src.open(ctx))
        if not self.keys:
            yield from rows
            return

        # `sort_rows` is the rows we'll sort.  By default it's the
        # upstream-projected rows; we may switch to base rows below
        # if a sort key isn't in the projected columns.
        sort_rows = rows
        post_proj_indices = None

        if isinstance(self.src, AggregatePlan):
            col_idx = {col: i for i, col in enumerate(self.src.keys)}
            synth_offset = len(self.src.keys)
            for i, (func, column) in enumerate(self.src.aggregates):
                col_idx[f"{func}({column})"] = synth_offset + i
        elif isinstance(self.src, Project):
            base_idx = ctx.name_to_idx_for(self.table)
            proj_labels = list(self.src.columns)
            proj_idx = {c: i for i, c in enumerate(proj_labels)}
            needs_base = any(col not in proj_idx for col, _ in self.keys)
            if needs_base:
                # Re-open the upstream of Project (the underlying Scan)
                # and sort over the BASE table's rows, then project.
                sort_rows = list(self.src.src.open(ctx))
                col_idx = base_idx
                post_proj_indices = tuple(base_idx[c] for c in proj_labels)
            else:
                col_idx = proj_idx
        else:
            col_idx = ctx.name_to_idx_for(self.table)

        for col, _ in self.keys:
            if col not in col_idx:
                raise UnknownColumnError(f"{self.table}.{col}")

        sort_rows.sort(key=_sort_key(col_idx, self.keys))

        if post_proj_indices is not None:
            yield from (tuple(r[i] for i in post_proj_indices) for r in sort_rows)
        else:
            yield from sort_rows


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
    """Invert a comparable for DESC sort.  None is filtered upstream.

    Numeric / bool values are arithmetic-negated; everything else
    (str, bytes, Decimal, datetime, ...) is wrapped in a sentinel that
    reverses the ordering on the sort key — ``(0, value)`` sorts
    ascending against the rest of the key, so multiplying by ``-1``
    inverts the comparison naturally for non-numerics too.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return -value
    # Non-numeric: invert the natural order by flipping the (asc, val)
    # sort-tuple convention used below.  ``(1, 0)`` sorts BEFORE
    # ``(0, val)`` under the default tuple ordering, so non-numeric
    # DESC rows come last-but-one, not first.  This is the standard
    # trick for ordering non-numerics in reverse.
    return _NegMarker(value)


class _NegMarker:
    """Sort-key wrapper that flips ASC ordering on a non-numeric value.

    Two markers compare by their wrapped value but inverted: ``a < b``
    becomes ``b < a``.  Encoded tuples still keep the (asc, val) shape
    above the marker so NULL ordering continues to work.
    """
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __lt__(self, other: "_NegMarker") -> bool:
        if not isinstance(other, _NegMarker):
            return NotImplemented
        # Invert: a is "less than" b iff b < a in the natural order.
        return other.value < self.value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _NegMarker):
            return NotImplemented
        return self.value == other.value

    def __repr__(self) -> str:
        return f"_NegMarker({self.value!r})"


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


def result_columns(plan: Plan) -> Optional[Sequence[str]]:
    """Walk ``plan`` and return the result-row column labels.

    T-POLISH: lets the CLI replace the legacy ``col0``/``col1`` fallback
    with real names from the topmost plan that carries a ``.columns``
    attribute.  Returns ``None`` when no plan in the chain advertises
    columns (e.g. DML leaf plans, an empty ``SeqScan``) so the caller
    can decide whether to fall back.

    Walks ``Sort`` / ``Limit`` wrappers down to the underlying
    :class:`Project` or :class:`Aggregate`.  ``Aggregate`` exposes
    result columns as ``(group_keys..., agg_labels...)`` mirroring
    its row layout.
    """
    cur = plan
    # Strip Limit / Sort wrappers (they don't carry output columns).
    while isinstance(cur, (Limit, Sort)):
        cur = cur.src
    if isinstance(cur, Project):
        return list(cur.columns)
    if isinstance(cur, Aggregate):
        agg_labels = [f"{func}({col})" for func, col in cur.aggregates]
        return list(cur.keys) + agg_labels
    return None


# Lazy re-export for Aggregate — its module imports Plan from here,
# so a top-level import is circular.  ``__getattr__`` resolves it
# the first time something does ``from tinydb.executor.ops import
# Aggregate`` (or accesses ``ops.Aggregate`` after ``import ops``).
_AGGREGATE = "Aggregate"
_LAZY: dict = {_AGGREGATE: ("tinydb.executor.aggregate", "Aggregate")}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_name, attr = target
    import importlib
    mod = importlib.import_module(mod_name)
    value = getattr(mod, attr)
    globals()[name] = value  # cache for subsequent access
    return value


__all__ = [
    "Plan",
    "Row",
    "SeqScan",
    "IndexScan",
    "Filter",
    "Project",
    "Sort",
    "Limit",
    "Aggregate",
    "result_columns",
    # Re-exported from tinydb.executor.dml for backward compatibility.
    "Insert",
    "Update",
    "Delete",
]