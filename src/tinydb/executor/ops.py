"""Plan tree dataclasses — AST → execution-plan translation layer.

Each :class:`Plan` subclass is a frozen, slotted dataclass carrying the
opaque fields a downstream executor will need to materialize rows.
T-5.1 only fixes the *shape* of the tree; T-5.2..5.6 implement the
iterators (``open``) that turn plans into :class:`Row` streams.

Immutability
------------
Every Plan is ``@dataclass(frozen=True, slots=True)`` so two identical
plan trees are interchangeable and the executor can cache / hash them
freely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Optional, Sequence


# A row is a tuple of bytes-encoded column values in declared column order.
Row = tuple


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    """Marker base — concrete plans are subclasses below.

    ``op_name`` is a class-level discriminator: subclasses set their own
    ``op_name`` as a default.  This avoids the dataclass-with-inheritance
    ``super().__init__`` pitfall (a frozen+slotted subclass cannot call
    ``super().__init__`` after ``__init__`` is generated for the child).
    """

    op_name: str = "Plan"

    def open(self, ctx: "Executor") -> Iterator[Row]:  # noqa: F821
        """Produce the row stream for this plan.  T-5.2 fills this in."""
        raise NotImplementedError("T-5.2 will implement actual execution")

    def __iter__(self) -> Iterator[Row]:  # pragma: no cover - convenience
        return self.open(None)  # type: ignore[arg-type]


# ``op_name`` defaults below are set via ``field(default=...)`` because
# dataclass() reads class annotations and a plain class attribute would
# become a regular instance attribute.  Each subclass sets its own
# discriminator so debug logs can switch on a single string field.


@dataclass(frozen=True, slots=True, kw_only=True)
class SeqScan(Plan):
    """Scan every row of ``table`` in heap order.

    The placeholder executor raises ``NotImplementedError``; T-5.2 will
    bind a :class:`~tinydb.storage.heap.Heap` from ``catalog`` and yield
    each row tuple in declared column order.
    """

    table: str
    op_name: str = "SeqScan"


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexScan(Plan):
    """Range scan over a single-column index.

    ``lo`` / ``hi`` are ``None`` for open-ended bounds; ``lo_inclusive``
    and ``hi_inclusive`` mirror SQL's ``[)`` semantics for ordered
    ranges.  T-5.3 will populate this branch from
    :func:`tinydb.executor.planner._try_index_plan`.
    """

    table: str
    index: str
    lo: Any = None
    hi: Any = None
    lo_inclusive: bool = True
    hi_inclusive: bool = True
    op_name: str = "IndexScan"


@dataclass(frozen=True, slots=True, kw_only=True)
class Filter(Plan):
    """Filter ``src`` rows using a predicate (an :class:`Expr` AST node)."""

    src: Plan
    predicate: object  # Expr from tinydb.sql.ast
    op_name: str = "Filter"


@dataclass(frozen=True, slots=True, kw_only=True)
class Project(Plan):
    """Project ``src`` rows onto the declared ``columns``.

    For ``SELECT *`` the planner produces a Project listing every
    column of the table in declared order (so the executor sees a
    uniform shape regardless of the SQL form).
    """

    src: Plan
    columns: Sequence[str]
    op_name: str = "Project"


@dataclass(frozen=True, slots=True, kw_only=True)
class Sort(Plan):
    """Sort ``src`` rows by ``keys``; optional ``limit`` + ``offset``.

    ``keys`` is a sequence of ``(column, descending)`` tuples — the
    planner emits ``(col, False)`` for ASC and ``(col, True)`` for
    DESC.  An empty ``keys`` sequence with a ``limit`` is legal (the
    executor treats it as "take the first N rows in input order").
    """

    src: Plan
    keys: Sequence[tuple]  # (column, descending: bool)
    limit: Optional[int] = None
    offset: int = 0
    op_name: str = "Sort"


# alias to satisfy the brief — T-5.4 will narrow Sort into Limit + Sort
Limit = Sort


@dataclass(frozen=True, slots=True, kw_only=True)
class Insert(Plan):
    """Insert one row into ``table``.

    ``values`` is a single-row tuple (matching the AST's outer-tuple
    shape so the planner can forward ``Insert.values[0]`` unchanged).
    """

    table: str
    values: tuple
    op_name: str = "Insert"


@dataclass(frozen=True, slots=True, kw_only=True)
class Update(Plan):
    """Update rows of ``table`` selected by ``predicate``.

    ``predicate`` is ``None`` to mean "update every row".
    """

    table: str
    assignments: Sequence[tuple]  # (column, Expr)
    predicate: object  # Expr | None
    op_name: str = "Update"


@dataclass(frozen=True, slots=True, kw_only=True)
class Delete(Plan):
    """Delete rows of ``table`` selected by ``predicate``.

    ``predicate`` is ``None`` to mean "delete every row".
    """

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