"""Tests for ORDER BY / LIMIT / GROUP BY / aggregate clauses.

T-3.5 RED phase.  Covers REQ-SQL-4 (ORDER BY direction + LIMIT/OFFSET)
and REQ-SQL-6 (GROUP BY + aggregate functions COUNT/SUM/AVG/MIN/MAX).

These clauses extend the SELECT statement parsed by T-3.4b; the public
entry point remains :func:`tinydb.sql.parser.parse_dml` and the AST
node is still :class:`~tinydb.sql.ast.Select`.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError
from tinydb.sql.ast import Aggregate, ColumnRef, OrderBy
from tinydb.sql.parser import parse_dml
from tinydb.sql.tokens import tokenize


def _dml(sql: str):
    return parse_dml(tokenize(sql))


# --- ORDER BY (REQ-SQL-4) -----------------------------------------------


@pytest.mark.unit
def test_order_by_default_is_ascending():
    stmt = _dml("SELECT * FROM t ORDER BY age")
    assert stmt.order_by == (OrderBy(column="age", descending=False),)


@pytest.mark.unit
def test_order_by_descending():
    stmt = _dml("SELECT * FROM t ORDER BY age DESC")
    assert stmt.order_by == (OrderBy(column="age", descending=True),)


@pytest.mark.unit
def test_order_by_explicit_ascending_keyword():
    stmt = _dml("SELECT * FROM t ORDER BY age ASC")
    assert stmt.order_by == (OrderBy(column="age", descending=False),)


@pytest.mark.unit
def test_order_by_multiple_columns_mixed_direction():
    stmt = _dml("SELECT * FROM t ORDER BY age DESC, name ASC, id")
    assert len(stmt.order_by) == 3
    assert stmt.order_by[0] == OrderBy(column="age", descending=True)
    assert stmt.order_by[1] == OrderBy(column="name", descending=False)
    assert stmt.order_by[2] == OrderBy(column="id", descending=False)


# --- LIMIT / OFFSET (REQ-SQL-4) -----------------------------------------


@pytest.mark.unit
def test_limit_alone():
    stmt = _dml("SELECT * FROM t LIMIT 10")
    assert stmt.limit == 10
    assert stmt.offset is None


@pytest.mark.unit
def test_limit_with_offset_keyword():
    stmt = _dml("SELECT * FROM t LIMIT 10 OFFSET 20")
    assert stmt.limit == 10
    assert stmt.offset == 20


# --- GROUP BY (REQ-SQL-6) -----------------------------------------------


@pytest.mark.unit
def test_group_by_single_column():
    stmt = _dml("SELECT dept FROM employees GROUP BY dept")
    assert stmt.group_by == ("dept",)


@pytest.mark.unit
def test_group_by_multiple_columns():
    stmt = _dml("SELECT dept, team FROM employees GROUP BY dept, team")
    assert stmt.group_by == ("dept", "team")


# --- aggregate functions (REQ-SQL-6) ------------------------------------


@pytest.mark.unit
def test_count_star_aggregate():
    stmt = _dml("SELECT COUNT(*) FROM users")
    assert stmt.columns == (Aggregate(func="COUNT", column="*"),)


@pytest.mark.unit
def test_count_column_aggregate():
    stmt = _dml("SELECT COUNT(id) FROM users")
    assert stmt.columns == (Aggregate(func="COUNT", column="id"),)


@pytest.mark.unit
def test_sum_aggregate():
    stmt = _dml("SELECT SUM(amount) FROM orders")
    assert stmt.columns == (Aggregate(func="SUM", column="amount"),)


@pytest.mark.unit
def test_avg_aggregate():
    stmt = _dml("SELECT AVG(age) FROM users")
    assert stmt.columns == (Aggregate(func="AVG", column="age"),)


@pytest.mark.unit
def test_min_max_aggregates():
    assert _dml("SELECT MIN(price) FROM products").columns[0] == Aggregate(
        func="MIN", column="price"
    )
    assert _dml("SELECT MAX(price) FROM products").columns[0] == Aggregate(
        func="MAX", column="price"
    )


@pytest.mark.unit
def test_aggregate_with_group_by_combined():
    stmt = _dml("SELECT dept, COUNT(*) FROM employees GROUP BY dept")
    assert len(stmt.columns) == 2
    assert stmt.columns[0] == ColumnRef(name="dept")
    assert stmt.columns[1] == Aggregate(func="COUNT", column="*")
    assert stmt.group_by == ("dept",)


@pytest.mark.unit
def test_multiple_aggregates_in_column_list():
    stmt = _dml("SELECT COUNT(*), SUM(amount), AVG(age) FROM users")
    assert stmt.columns == (
        Aggregate(func="COUNT", column="*"),
        Aggregate(func="SUM", column="amount"),
        Aggregate(func="AVG", column="age"),
    )


# --- combined clauses ---------------------------------------------------


@pytest.mark.unit
def test_where_order_by_limit_combined():
    stmt = _dml(
        "SELECT * FROM users WHERE age >= 18 ORDER BY name LIMIT 100 OFFSET 10"
    )
    assert stmt.where.op == ">="
    assert stmt.order_by == (OrderBy(column="name", descending=False),)
    assert stmt.limit == 100
    assert stmt.offset == 10


# --- error reporting ----------------------------------------------------


@pytest.mark.unit
def test_limit_without_number_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("SELECT * FROM t LIMIT")


@pytest.mark.unit
def test_order_by_without_column_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("SELECT * FROM t ORDER BY")


@pytest.mark.unit
def test_group_by_without_column_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("SELECT dept FROM t GROUP BY")