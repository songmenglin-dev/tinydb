"""Planner-side predicate matcher for :class:`IndexScan`.

T-5.3 wires the planner to the index layer: given a WHERE clause AST
and the table's column names, :func:`extract_indexable` decides whether
the WHERE can be served by a single-column index scan (equality, range
or AND-of-same-column bounds).

Out of scope: multi-column predicates (composite keys — T-5.5),
OR-of-ranges across different columns, IS NULL/IS NOT NULL (NULLs are
not in the B-tree; executor falls back to SeqScan).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from tinydb.sql.ast import BinaryOp, ColumnRef, Expr, Literal, TypedLiteral

_INDEXABLE_OPS = frozenset({"=", "<", "<=", ">", ">="})
_LOWER_OPS = frozenset({">", ">="})
_UPPER_OPS = frozenset({"<", "<="})


@dataclass(frozen=True, slots=True)
class IndexablePredicate:
    """A single-column predicate extracted from a WHERE clause.

    Equality lives in ``op``/``value``; a second bound (range merge) in
    ``hi_op``/``hi_value``.  Callers must check both — the merge step
    may emit either bound as the primary.
    """

    column: str
    op: str
    value: Any
    hi_op: Optional[str] = None
    hi_value: Optional[Any] = None


def extract_indexable(
    where: Expr, table_columns: Tuple[str, ...]
) -> Optional[IndexablePredicate]:
    """Pull a single-column equality or range off the WHERE clause."""
    known = set(table_columns)
    if isinstance(where, BinaryOp) and where.op == "AND":
        left = extract_indexable(where.left, table_columns)
        right = extract_indexable(where.right, table_columns)
        if left is None or right is None:
            return None
        if left.column != right.column:
            return None
        return _merge_same_column(left, right)
    return _single_bound(where, known)


def _single_bound(expr: Expr, known: set) -> Optional[IndexablePredicate]:
    if not isinstance(expr, BinaryOp) or expr.op not in _INDEXABLE_OPS:
        return None
    col, lit = _split_col_lit(expr.left, expr.right, known)
    if col is None or lit is None:
        return None
    return IndexablePredicate(column=col, op=expr.op, value=lit)


def _split_col_lit(left: Expr, right: Expr, known: set):
    """Return ``(column_name, literal_value)`` for a ``col op lit`` shape."""
    if isinstance(left, ColumnRef) and left.name in known and _is_literal(right):
        return left.name, right.value
    if isinstance(right, ColumnRef) and right.name in known and _is_literal(left):
        return right.name, left.value
    return None, None


def _is_literal(expr: Expr) -> bool:
    return isinstance(expr, (Literal, TypedLiteral))


def _merge_same_column(a: IndexablePredicate, b: IndexablePredicate) -> IndexablePredicate:
    """Combine two same-column bounds into one range.

    For ``col >= a AND col >= b`` the tighter lower bound (``max``) wins;
    same for the upper bound.  Contradictory bounds (e.g. ``col >= 10
    AND col <= 5``) flow through naturally — the range yields ``[]``.
    """
    if a.op in _LOWER_OPS and b.op in _UPPER_OPS:
        return IndexablePredicate(a.column, a.op, a.value, b.op, b.value)
    if a.op in _UPPER_OPS and b.op in _LOWER_OPS:
        return IndexablePredicate(b.column, b.op, b.value, a.op, a.value)
    if a.op in _LOWER_OPS and b.op in _LOWER_OPS:
        return _merge_lower(a, b)
    if a.op in _UPPER_OPS and b.op in _UPPER_OPS:
        return _merge_upper(a, b)
    # Equality + something — keep equality as the primary.
    return IndexablePredicate(a.column, a.op, a.value, b.op, b.value)


def _tighter_lower(a: IndexablePredicate, b: IndexablePredicate) -> IndexablePredicate:
    """Lower bound: keep the larger floor; ``>`` wins over ``>=`` at equal value."""
    if a.value > b.value:
        return a
    if b.value > a.value:
        return b
    # Equal values: strict ">" wins because it's a tighter floor.
    return a if a.op == ">" else b


def _tighter_upper(a: IndexablePredicate, b: IndexablePredicate) -> IndexablePredicate:
    """Upper bound: keep the smaller ceiling; ``<`` wins over ``<=`` at equal value."""
    if a.value < b.value:
        return a
    if b.value < a.value:
        return b
    return a if a.op == "<" else b


def _merge_lower(a: IndexablePredicate, b: IndexablePredicate) -> IndexablePredicate:
    # Strict ">" beats inclusive ">=" when the strict value is at
    # least as tight; otherwise the inclusive one is the safer floor.
    if a.op == ">" and b.op == ">=":
        return a if a.value >= b.value else b
    if a.op == ">=" and b.op == ">":
        return b if b.value >= a.value else a
    return _tighter_lower(a, b)


def _merge_upper(a: IndexablePredicate, b: IndexablePredicate) -> IndexablePredicate:
    if a.op == "<" and b.op == "<=":
        return a if a.value <= b.value else b
    if a.op == "<=" and b.op == "<":
        return b if b.value <= a.value else a
    return _tighter_upper(a, b)


__all__ = ["IndexablePredicate", "extract_indexable"]
