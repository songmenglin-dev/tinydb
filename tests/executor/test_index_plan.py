"""T-5.3 — planner-side predicate matching for IndexScan.

These tests exercise :func:`tinydb.executor.index_plan.extract_indexable`
in isolation: build an Expr AST manually (no SQL parsing) and assert that
the planner surfaces the right :class:`IndexablePredicate`.

The ``table_columns`` argument simulates the table schema; the predicate
matcher only needs column names to decide whether a predicate is
indexable on a single column.
"""

from __future__ import annotations

from tinydb.executor.index_plan import IndexablePredicate, extract_indexable
from tinydb.sql.ast import BinaryOp, ColumnRef, Literal, TypedLiteral, UnaryOp
from tinydb.types.system import TypeTag


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_TABLE_COLS = ("id", "name", "age")


def _col(name: str) -> ColumnRef:
    return ColumnRef(name=name)


def _lit(value) -> Literal:
    return Literal(value=value)


# ---------------------------------------------------------------------------
# 1. col = 1  →  (col, '=', 1)
# ---------------------------------------------------------------------------


def test_equality_predicate_right_literal():
    """`col = 1` with literal on the right side is indexable."""
    pred = BinaryOp("=", _col("id"), _lit(1))
    out = extract_indexable(pred, _TABLE_COLS)
    assert out == IndexablePredicate(column="id", op="=", value=1)


# ---------------------------------------------------------------------------
# 2. 1 = col  →  same shape (literal on the left side)
# ---------------------------------------------------------------------------


def test_equality_predicate_left_literal():
    """`1 = col` swaps and matches the same IndexablePredicate."""
    pred = BinaryOp("=", _lit(1), _col("id"))
    out = extract_indexable(pred, _TABLE_COLS)
    assert out == IndexablePredicate(column="id", op="=", value=1)


# ---------------------------------------------------------------------------
# 3. col >= 5  →  (col, '>=', 5)
# ---------------------------------------------------------------------------


def test_greater_equal_predicate():
    """`col >= 5` surfaces as a range lower-bound with op='>='."""
    pred = BinaryOp(">=", _col("age"), _lit(5))
    out = extract_indexable(pred, _TABLE_COLS)
    assert out == IndexablePredicate(column="age", op=">=", value=5)


# ---------------------------------------------------------------------------
# 4. col < 100  →  (col, '<', 100)
# ---------------------------------------------------------------------------


def test_less_than_predicate():
    """`col < 100` surfaces as op='<'."""
    pred = BinaryOp("<", _col("age"), _lit(100))
    out = extract_indexable(pred, _TABLE_COLS)
    assert out == IndexablePredicate(column="age", op="<", value=100)


# ---------------------------------------------------------------------------
# 5. AND of same column  →  range: lo <= col <= hi
# ---------------------------------------------------------------------------


def test_and_same_column_merges_to_range():
    """`col >= 5 AND col <= 10` collapses into a range on the same column."""
    pred = BinaryOp(
        "AND",
        BinaryOp(">=", _col("age"), _lit(5)),
        BinaryOp("<=", _col("age"), _lit(10)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    # The implementation may surface either bound as the primary; the
    # important contract is that BOTH bounds appear and the column
    # matches.
    assert out is not None
    assert out.column == "age"
    assert {out.op, out.hi_op} == {">=", "<="}
    # Either ordering is acceptable; check both bounds.
    if out.op == ">=":
        assert out.value == 5
        assert out.hi_value == 10
    else:
        assert out.value == 10
        assert out.hi_value == 5


# ---------------------------------------------------------------------------
# 6. AND of different columns  →  None
# ---------------------------------------------------------------------------


def test_and_different_columns_returns_none():
    """`col_a = 1 AND col_b = 2` is not a single-column indexable predicate."""
    pred = BinaryOp(
        "AND",
        BinaryOp("=", _col("id"), _lit(1)),
        BinaryOp("=", _col("name"), _lit("alice")),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is None


# ---------------------------------------------------------------------------
# 7. col IS NULL  →  None (not indexable in v0.1)
# ---------------------------------------------------------------------------


def test_is_null_not_indexable():
    """`col IS NULL` returns None — NULLs are not in the B-tree."""
    pred = UnaryOp("IS NULL", _col("age"))
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is None


# ---------------------------------------------------------------------------
# 8. AND of `col >= a AND col <= b` (BETWEEN canonical form)  →  range
# ---------------------------------------------------------------------------


def test_between_canonical_form():
    """`BETWEEN a AND b` parses as `col >= a AND col <= b`."""
    pred = BinaryOp(
        "AND",
        BinaryOp(">=", _col("age"), _lit(5)),
        BinaryOp("<=", _col("age"), _lit(10)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is not None
    assert out.column == "age"


# ---------------------------------------------------------------------------
# 9. col + 1 = 5  →  None (arithmetic on column side)
# ---------------------------------------------------------------------------


def test_arithmetic_on_column_not_indexable():
    """`col + 1 = 5` has an arithmetic BinaryOp on the column side → None."""
    pred = BinaryOp(
        "=",
        BinaryOp("+", _col("age"), _lit(1)),
        _lit(5),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is None


# ---------------------------------------------------------------------------
# 10. TypedLiteral (e.g. DATE '2026-01-01') as the literal  →  indexable
# ---------------------------------------------------------------------------


def test_typed_literal_equality():
    """A TypedLiteral on the right side is indexable just like a Literal."""
    pred = BinaryOp(
        "=",
        _col("id"),
        TypedLiteral(tag=TypeTag.Int, value=42),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out == IndexablePredicate(column="id", op="=", value=42)


# ---------------------------------------------------------------------------
# coverage extensions — exercise the merge / corner paths
# ---------------------------------------------------------------------------


def test_lower_bound_merge_picks_max():
    """AND of two lower bounds (>=5 AND >=10) picks the larger value."""
    pred = BinaryOp(
        "AND",
        BinaryOp(">=", _col("age"), _lit(5)),
        BinaryOp(">=", _col("age"), _lit(10)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is not None
    assert out.column == "age"
    assert out.op == ">="
    assert out.value == 10  # the tighter (larger) lower bound


def test_upper_bound_merge_picks_min():
    """AND of two upper bounds (<=20 AND <=30) picks the smaller value."""
    pred = BinaryOp(
        "AND",
        BinaryOp("<=", _col("age"), _lit(30)),
        BinaryOp("<=", _col("age"), _lit(20)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is not None
    assert out.column == "age"
    assert out.op == "<="
    assert out.value == 20  # the tighter (smaller) upper bound


def test_strict_lower_beats_inclusive_lower():
    """`> 10` beats `>= 5` because 10 > 5."""
    pred = BinaryOp(
        "AND",
        BinaryOp(">=", _col("age"), _lit(5)),
        BinaryOp(">", _col("age"), _lit(10)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is not None
    assert out.op == ">"
    assert out.value == 10


def test_equality_collapses_with_range():
    """`col = 5 AND col >= 3` surfaces equality as the lower bound."""
    pred = BinaryOp(
        "AND",
        BinaryOp("=", _col("age"), _lit(5)),
        BinaryOp(">=", _col("age"), _lit(3)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is not None
    assert out.column == "age"


def test_arithmetic_on_left_not_indexable():
    """Arithmetic on the column side returns None (only Literal/ColumnRef)."""
    pred = BinaryOp(
        "=",
        _lit(5),
        BinaryOp("+", _col("age"), _lit(1)),
    )
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is None


def test_non_comparison_op_returns_none():
    """`+` is arithmetic — not an indexable comparison."""
    pred = BinaryOp("+", _col("age"), _lit(1))
    out = extract_indexable(pred, _TABLE_COLS)
    assert out is None