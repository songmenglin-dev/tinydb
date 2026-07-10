"""Tests for the DML subset of the SQL parser.

T-3.4b RED phase.  Covers REQ-SQL-2: INSERT / SELECT / UPDATE / DELETE
with their optional WHERE clauses (the WHERE expression reuses the
T-3.4a expression parser).  ORDER BY / LIMIT / GROUP BY / aggregates
are covered by T-3.5; this task only proves the basic statement
shapes parse and dispatch to the correct AST node.

The public entry point is :func:`tinydb.sql.parser.parse_dml`; it
dispatches on the leading keyword and raises :class:`ParseError` with
the offending token's line / column on malformed input.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError
from tinydb.sql.ast import (
    Assignment,
    BinaryOp,
    ColumnRef,
    Delete,
    Insert,
    Literal,
    Select,
    Star,
    Update,
)
from tinydb.sql.parser import parse_dml
from tinydb.sql.tokens import tokenize


# --- helpers ------------------------------------------------------------


def _dml(sql: str):
    """Lex + parse a single DML statement."""
    return parse_dml(tokenize(sql))


# --- INSERT -------------------------------------------------------------


@pytest.mark.unit
def test_insert_with_column_list_single_row():
    stmt = _dml("INSERT INTO users (id, name) VALUES (1, 'alice')")
    assert isinstance(stmt, Insert)
    assert stmt.table == "users"
    assert stmt.columns == ("id", "name")
    assert stmt.values == ((1, "alice"),)


@pytest.mark.unit
def test_insert_with_column_list_multiple_rows():
    stmt = _dml(
        "INSERT INTO users (id, name) VALUES (1, 'a'), (2, 'b'), (3, 'c')"
    )
    assert stmt.values == ((1, "a"), (2, "b"), (3, "c"))


@pytest.mark.unit
def test_insert_without_column_list_means_full_row():
    """``INSERT INTO t VALUES (...)`` — columns=None means full-row insert."""
    stmt = _dml("INSERT INTO t VALUES (42, 'hello')")
    assert stmt.table == "t"
    assert stmt.columns is None
    assert stmt.values == ((42, "hello"),)


@pytest.mark.unit
def test_insert_with_null_and_bool_values():
    stmt = _dml("INSERT INTO t (a, b, c) VALUES (NULL, TRUE, FALSE)")
    assert stmt.values == ((None, True, False),)


@pytest.mark.unit
def test_insert_with_float_value():
    stmt = _dml("INSERT INTO prices (id, amount) VALUES (1, 9.99)")
    assert stmt.values[0][1] == 9.99


# --- SELECT -------------------------------------------------------------


@pytest.mark.unit
def test_select_star_from_table():
    stmt = _dml("SELECT * FROM users")
    assert isinstance(stmt, Select)
    assert stmt.columns == (Star(),)
    assert stmt.table == "users"
    assert stmt.where is None


@pytest.mark.unit
def test_select_multiple_columns_from_table():
    stmt = _dml("SELECT id, name FROM users")
    assert stmt.columns == (ColumnRef(name="id"), ColumnRef(name="name"))
    assert stmt.table == "users"


@pytest.mark.unit
def test_select_with_where_comparison():
    stmt = _dml("SELECT id FROM users WHERE age >= 18")
    assert stmt.where.op == ">="
    assert stmt.where.left == ColumnRef(name="age")
    assert stmt.where.right == Literal(value=18)


@pytest.mark.unit
def test_select_with_compound_where():
    """WHERE reuses the expression parser — AND chains both sides."""
    stmt = _dml(
        "SELECT id FROM users WHERE age >= 18 AND status = 'active'"
    )
    assert stmt.where.op == "AND"
    assert stmt.where.left.op == ">="
    assert stmt.where.right.op == "="


@pytest.mark.unit
def test_select_with_is_null_where():
    stmt = _dml("SELECT id FROM users WHERE deleted_at IS NULL")
    assert stmt.where.op == "IS NULL"
    assert stmt.where.operand == ColumnRef(name="deleted_at")


@pytest.mark.unit
def test_select_with_arithmetic_expression_in_column_list():
    """Column lists accept arbitrary expressions, not just column refs."""
    stmt = _dml("SELECT price * 1.1 FROM products")
    assert stmt.columns[0].op == "*"


@pytest.mark.unit
def test_select_qualified_column_in_where():
    stmt = _dml("SELECT id FROM users WHERE users.age > 18")
    assert stmt.where.left == ColumnRef(name="age", table="users")


# --- UPDATE -------------------------------------------------------------


@pytest.mark.unit
def test_update_single_assignment_no_where():
    stmt = _dml("UPDATE users SET name = 'bob'")
    assert isinstance(stmt, Update)
    assert stmt.table == "users"
    assert stmt.set_clauses == (
        Assignment(column="name", value=Literal(value="bob")),
    )
    assert stmt.where is None


@pytest.mark.unit
def test_update_multiple_assignments():
    stmt = _dml("UPDATE users SET name = 'b', age = 30")
    assert len(stmt.set_clauses) == 2
    assert stmt.set_clauses[0].column == "name"
    assert stmt.set_clauses[1].column == "age"


@pytest.mark.unit
def test_update_with_where():
    stmt = _dml("UPDATE users SET name = 'b' WHERE id = 1")
    assert stmt.where.op == "="
    assert stmt.where.left == ColumnRef(name="id")


# --- DELETE -------------------------------------------------------------


@pytest.mark.unit
def test_delete_without_where():
    stmt = _dml("DELETE FROM users")
    assert isinstance(stmt, Delete)
    assert stmt.table == "users"
    assert stmt.where is None


@pytest.mark.unit
def test_delete_with_where():
    stmt = _dml("DELETE FROM users WHERE id = 1")
    assert stmt.where.op == "="
    assert stmt.where.left == ColumnRef(name="id")


# --- error reporting ----------------------------------------------------


@pytest.mark.unit
def test_select_without_from_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("SELECT id")


@pytest.mark.unit
def test_update_without_set_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("UPDATE users")


@pytest.mark.unit
def test_insert_missing_values_keyword_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("INSERT INTO users (id) (1)")


@pytest.mark.unit
def test_delete_without_table_raises_parse_error():
    with pytest.raises(ParseError):
        _dml("DELETE FROM")