"""Tests for the expression parser.

T-3.4a RED phase.  Covers REQ-SQL-3 (arithmetic + comparison),
REQ-SQL-4 partial (logical AND/OR + precedence), REQ-SQL-8 (literal
classification reused from the lexer), REQ-TYP-7 (NULL semantics).

The parser entry point ``parse_expr(tokens) -> Expr`` consumes a
pre-tokenised stream (typically the tail of a WHERE / SET / VALUES
clause) and returns a frozen-dataclass :class:`Expr` tree.  Operator
precedence climbs from OR (lowest) through AND, comparison,
additive, multiplicative, unary, to primary.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError
from tinydb.sql.parser import parse_expr
from tinydb.sql.tokens import tokenize
from tinydb.sql.ast import (
    BinaryOp,
    ColumnRef,
    Literal,
    UnaryOp,
)


# --- helpers ------------------------------------------------------------


def _e(sql: str):
    """Lex + parse a single expression."""
    return parse_expr(tokenize(sql))


# --- literals ------------------------------------------------------------


@pytest.mark.unit
def test_int_literal():
    assert _e("42") == Literal(value=42)


@pytest.mark.unit
def test_float_literal():
    assert _e("3.14") == Literal(value=3.14)


@pytest.mark.unit
def test_string_literal():
    assert _e("'hello'") == Literal(value="hello")


@pytest.mark.unit
def test_bool_literal():
    assert _e("TRUE") == Literal(value=True)
    assert _e("FALSE") == Literal(value=False)


@pytest.mark.unit
def test_null_literal():
    assert _e("NULL") == Literal(value=None)


# --- column references --------------------------------------------------


@pytest.mark.unit
def test_simple_column_reference():
    assert _e("id") == ColumnRef(name="id")


@pytest.mark.unit
def test_qualified_column_reference():
    """``t.col`` parses as a ColumnRef with table qualifier."""
    assert _e("users.id") == ColumnRef(name="id", table="users")


# --- arithmetic & comparison (REQ-SQL-3) -------------------------------


@pytest.mark.unit
def test_addition():
    expr = _e("a + b")
    assert expr == BinaryOp(
        op="+", left=ColumnRef(name="a"), right=ColumnRef(name="b")
    )


@pytest.mark.unit
def test_subtraction_and_division():
    assert _e("a - b").op == "-"
    assert _e("a / b").op == "/"
    assert _e("a * b").op == "*"


@pytest.mark.unit
def test_arithmetic_precedence_multiplication_binds_tighter():
    """``1 + 2 * 3`` parses as ``1 + (2 * 3)``."""
    expr = _e("1 + 2 * 3")
    assert expr.op == "+"
    assert expr.left == Literal(value=1)
    assert expr.right.op == "*"
    assert expr.right.left == Literal(value=2)
    assert expr.right.right == Literal(value=3)


@pytest.mark.unit
def test_left_associative_subtraction():
    """``a - b - c`` parses as ``(a - b) - c``."""
    expr = _e("a - b - c")
    assert expr.op == "-"
    assert expr.left.op == "-"
    assert expr.right == ColumnRef(name="c")


@pytest.mark.unit
def test_comparison_operators():
    for op in ("=", "!=", "<", "<=", ">", ">="):
        expr = _e(f"a {op} b")
        assert expr.op == op
        assert expr.left == ColumnRef(name="a")
        assert expr.right == ColumnRef(name="b")


@pytest.mark.unit
def test_comparison_with_literal_on_right():
    expr = _e("age >= 18")
    assert expr.op == ">="
    assert expr.left == ColumnRef(name="age")
    assert expr.right == Literal(value=18)


# --- logical operators (REQ-SQL-4) --------------------------------------


@pytest.mark.unit
def test_and_chains_two_comparisons():
    expr = _e("a > 1 AND b < 2")
    assert expr.op == "AND"
    assert expr.left.op == ">"
    assert expr.right.op == "<"


@pytest.mark.unit
def test_or_chains_two_comparisons():
    expr = _e("a = 1 OR b = 2")
    assert expr.op == "OR"


@pytest.mark.unit
def test_and_binds_tighter_than_or():
    """``a OR b AND c`` parses as ``a OR (b AND c)``."""
    expr = _e("a OR b AND c")
    assert expr.op == "OR"
    assert expr.left == ColumnRef(name="a")
    assert expr.right.op == "AND"


@pytest.mark.unit
def test_multiple_or_left_associative():
    expr = _e("a OR b OR c")
    assert expr.op == "OR"
    assert expr.left.op == "OR"
    assert expr.right == ColumnRef(name="c")


# --- parentheses override precedence -----------------------------------


@pytest.mark.unit
def test_parenthesised_expression_overrides_precedence():
    """``(a + b) * c`` parses as the explicit grouping."""
    expr = _e("(a + b) * c")
    assert expr.op == "*"
    assert expr.left.op == "+"
    assert expr.right == ColumnRef(name="c")


@pytest.mark.unit
def test_nested_parentheses():
    expr = _e("((x))")
    # Stripping parens: the AST should equal the inner ColumnRef.
    assert expr == ColumnRef(name="x")


# --- unary operators (NOT, IS NULL, unary minus) -----------------------


@pytest.mark.unit
def test_not_operator():
    expr = _e("NOT x")
    assert expr == UnaryOp(op="NOT", operand=ColumnRef(name="x"))


@pytest.mark.unit
def test_double_not():
    """``NOT NOT x`` is two nested UnaryOp nodes."""
    expr = _e("NOT NOT x")
    assert expr.op == "NOT"
    assert expr.operand.op == "NOT"
    assert expr.operand.operand == ColumnRef(name="x")


@pytest.mark.unit
def test_is_null():
    expr = _e("x IS NULL")
    assert expr == UnaryOp(op="IS NULL", operand=ColumnRef(name="x"))


@pytest.mark.unit
def test_is_not_null_accepts_both_keyword_and_null_lit():
    """Lexer emits NULL as NULL_LIT — parser must accept both spellings."""
    a = _e("x IS NOT NULL")
    b = _e("x IS NOT NULL")  # same input
    assert a == UnaryOp(op="IS NOT NULL", operand=ColumnRef(name="x"))
    assert a == b


@pytest.mark.unit
def test_unary_minus():
    expr = _e("-x")
    assert expr == UnaryOp(op="-", operand=ColumnRef(name="x"))


@pytest.mark.unit
def test_unary_minus_on_literal():
    expr = _e("-42")
    assert expr == UnaryOp(op="-", operand=Literal(value=42))


# --- error reporting ----------------------------------------------------


@pytest.mark.unit
def test_unmatched_parenthesis_raises_parse_error():
    with pytest.raises(ParseError):
        _e("(a + b")


@pytest.mark.unit
def test_trailing_operator_raises_parse_error():
    with pytest.raises(ParseError):
        _e("a +")


@pytest.mark.unit
def test_empty_input_raises_parse_error():
    with pytest.raises(ParseError):
        _e("")


@pytest.mark.unit
def test_dot_without_rhs_raises_parse_error():
    """``users.`` (dot then EOF) is malformed."""
    with pytest.raises(ParseError):
        _e("users.")