"""Tests for the DDL subset of the SQL parser.

T-3.3 RED phase.  Covers REQ-SQL-1 (CREATE/DROP TABLE with constraints).
The parser entry point ``parse_ddl(tokens) -> CreateTable | DropTable``
consumes a token stream (already produced by :func:`tinydb.tokenize`)
and returns a frozen-dataclass AST node.  Position-aware :class:`ParseError`
is raised for every malformed input — the line/column of the offending
token is part of the test contract.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError
from tinydb.sql.parser import parse_ddl
from tinydb.sql.tokens import tokenize
from tinydb.types.system import Column, TypeTag


# --- helpers ------------------------------------------------------------


def _parse(sql: str):
    """Lex + parse a SQL string in one shot."""
    return parse_ddl(tokenize(sql))


@pytest.mark.unit
def test_create_table_single_int_column():
    stmt = _parse("CREATE TABLE users (id INT)")
    assert stmt.name == "users"
    assert stmt.columns == (Column(name="id", tag=TypeTag.Int),)


@pytest.mark.unit
def test_create_table_varchar_alias_maps_to_text():
    """VARCHAR is an alias for TEXT per parse_type_name."""
    stmt = _parse("CREATE TABLE t (name VARCHAR)")
    assert stmt.columns[0].tag is TypeTag.Text


@pytest.mark.unit
def test_create_table_multiple_mixed_type_columns():
    stmt = _parse(
        "CREATE TABLE products ("
        "  id INT,"
        "  name TEXT,"
        "  price FLOAT,"
        "  in_stock BOOL"
        ")"
    )
    assert stmt.name == "products"
    assert stmt.columns == (
        Column(name="id", tag=TypeTag.Int),
        Column(name="name", tag=TypeTag.Text),
        Column(name="price", tag=TypeTag.Float),
        Column(name="in_stock", tag=TypeTag.Bool),
    )


@pytest.mark.unit
def test_create_table_with_primary_key_constraint():
    stmt = _parse("CREATE TABLE users (id INT PRIMARY KEY)")
    col = stmt.columns[0]
    assert col.primary_key is True
    assert col.not_null is False
    assert col.unique is False


@pytest.mark.unit
def test_create_table_with_not_null_constraint():
    stmt = _parse("CREATE TABLE users (email TEXT NOT NULL)")
    assert stmt.columns[0].not_null is True


@pytest.mark.unit
def test_create_table_with_unique_constraint():
    stmt = _parse("CREATE TABLE users (email TEXT UNIQUE)")
    assert stmt.columns[0].unique is True


@pytest.mark.unit
def test_create_table_with_multiple_constraints_in_any_order():
    """SQL allows constraint order to vary — parser must accept any."""
    stmt = _parse(
        "CREATE TABLE users (id INT NOT NULL PRIMARY KEY UNIQUE)"
    )
    col = stmt.columns[0]
    assert col.not_null is True
    assert col.primary_key is True
    assert col.unique is True


@pytest.mark.unit
def test_create_table_ignores_varchar_size_suffix():
    """``VARCHAR(50)`` — size suffix is accepted but ignored in v0.1."""
    stmt = _parse("CREATE TABLE t (name VARCHAR(50))")
    assert stmt.columns[0].tag is TypeTag.Text


@pytest.mark.unit
def test_create_table_trailing_semicolon_is_optional():
    """A trailing ``;`` is accepted but not required."""
    a = _parse("CREATE TABLE t (id INT)")
    b = _parse("CREATE TABLE t (id INT);")
    assert a == b


@pytest.mark.unit
def test_drop_table_basic():
    stmt = _parse("DROP TABLE users")
    assert stmt.name == "users"
    assert stmt.if_exists is False


@pytest.mark.unit
def test_drop_table_if_exists():
    stmt = _parse("DROP TABLE IF EXISTS users")
    assert stmt.name == "users"
    assert stmt.if_exists is True


# --- error reporting ----------------------------------------------------


@pytest.mark.unit
def test_unknown_type_raises_parse_error_with_position():
    with pytest.raises(ParseError) as excinfo:
        _parse("CREATE TABLE t (x FOO)")
    msg = str(excinfo.value)
    # Position must be reported on the offending token.
    assert "line" in msg.lower() and "col" in msg.lower()


@pytest.mark.unit
def test_missing_type_raises_parse_error():
    """A column without a type is malformed."""
    with pytest.raises(ParseError):
        _parse("CREATE TABLE t (id)")


@pytest.mark.unit
def test_missing_table_name_raises_parse_error():
    with pytest.raises(ParseError):
        _parse("CREATE TABLE (id INT)")


@pytest.mark.unit
def test_unclosed_parenthesis_raises_parse_error():
    with pytest.raises(ParseError):
        _parse("CREATE TABLE t (id INT")


@pytest.mark.unit
def test_drop_table_without_name_raises_parse_error():
    with pytest.raises(ParseError):
        _parse("DROP TABLE")