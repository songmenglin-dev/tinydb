"""Tests for type-prefixed literals (DATE / TIME / DATETIME / DECIMAL / BLOB / JSON).

T-3.6 RED phase.  Covers REQ-TYP-9..14 at the parser surface:

* ``DATE 'YYYY-MM-DD'``            → ``TypedLiteral(Date, date)``
* ``TIME 'HH:MM:SS[.ffffff]'``     → ``TypedLiteral(Time, time)``
* ``DATETIME 'YYYY-MM-DD HH:MM:SS[.ffffff]'`` → ``TypedLiteral(Datetime, datetime)``
* ``DECIMAL 'N.NNN'``              → ``TypedLiteral(Decimal, Decimal)``
* ``BLOB 'hex'``                   → ``TypedLiteral(Blob, bytes)``
* ``JSON '{...}'``                 → ``TypedLiteral(Json, dict | list | scalar)``

The typed literal is a normal :class:`Expr` node, so it parses in any
expression position — WHERE / SET-clause / VALUES / SELECT-column list.
Malformed input raises :class:`ParseError` with line/column.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest

from tinydb.errors import ParseError
from tinydb.sql.ast import (
    BinaryOp,
    ColumnRef,
    Insert,
    Literal,
    TypedLiteral,
)
from tinydb.sql.parser import parse_dml, parse_expr
from tinydb.sql.tokens import tokenize
from tinydb.types.system import TypeTag


def _dml(sql: str):
    return parse_dml(tokenize(sql))


def _e(sql: str):
    return parse_expr(tokenize(sql))


# --- DATE (REQ-TYP-9) ---------------------------------------------------


@pytest.mark.unit
def test_date_literal_in_insert_values():
    stmt = _dml("INSERT INTO t (d) VALUES (DATE '2026-07-09')")
    assert isinstance(stmt, Insert)
    assert stmt.values == ((TypedLiteral(TypeTag.Date, datetime.date(2026, 7, 9)),),)


@pytest.mark.unit
def test_date_literal_in_where():
    expr = _e("d >= DATE '2026-01-01'")
    assert isinstance(expr, BinaryOp)
    assert expr.op == ">="
    assert expr.left == ColumnRef(name="d")
    assert expr.right == TypedLiteral(TypeTag.Date, datetime.date(2026, 1, 1))


@pytest.mark.unit
def test_invalid_date_format_raises_parse_error():
    with pytest.raises(ParseError) as excinfo:
        _e("DATE '2026-13-40'")
    assert "line" in str(excinfo.value).lower()


@pytest.mark.unit
def test_date_without_string_literal_raises_parse_error():
    """``DATE 42`` (no string) is malformed."""
    with pytest.raises(ParseError):
        _e("DATE 42")


# --- TIME (REQ-TYP-10) --------------------------------------------------


@pytest.mark.unit
def test_time_literal_basic():
    expr = _e("TIME '14:30:00'")
    assert expr == TypedLiteral(TypeTag.Time, datetime.time(14, 30, 0))


@pytest.mark.unit
def test_time_literal_with_microseconds():
    expr = _e("TIME '09:00:00.123456'")
    assert expr == TypedLiteral(TypeTag.Time, datetime.time(9, 0, 0, 123456))


@pytest.mark.unit
def test_time_literal_in_compound_where():
    """TIME literals mix with arithmetic / column refs in a WHERE expr."""
    expr = _e("t >= TIME '09:00:00' AND t <= TIME '17:00:00'")
    assert expr.op == "AND"
    assert expr.left.op == ">="
    assert expr.left.right == TypedLiteral(
        TypeTag.Time, datetime.time(9, 0, 0),
    )


# --- DATETIME (REQ-TYP-11) ----------------------------------------------


@pytest.mark.unit
def test_datetime_literal_full():
    expr = _e("DATETIME '2026-07-09 14:30:00'")
    assert expr == TypedLiteral(
        TypeTag.Datetime,
        datetime.datetime(2026, 7, 9, 14, 30, 0),
    )


@pytest.mark.unit
def test_datetime_literal_with_microseconds():
    expr = _e("DATETIME '2026-07-09 14:30:00.500000'")
    assert expr == TypedLiteral(
        TypeTag.Datetime,
        datetime.datetime(2026, 7, 9, 14, 30, 0, 500000),
    )


# --- DECIMAL (REQ-TYP-12) -----------------------------------------------


@pytest.mark.unit
def test_decimal_literal_basic():
    expr = _e("DECIMAL '1234.56'")
    assert expr == TypedLiteral(TypeTag.Decimal, Decimal("1234.56"))


@pytest.mark.unit
def test_decimal_literal_preserves_precision():
    """0.1 must NOT become 0.1000000000000000055..."""
    expr = _e("DECIMAL '0.10'")
    assert expr.value == Decimal("0.10")
    assert isinstance(expr.value, Decimal)


@pytest.mark.unit
def test_decimal_literal_negative():
    expr = _e("DECIMAL '-99.99'")
    assert expr.value == Decimal("-99.99")


# --- BLOB (REQ-TYP-13) --------------------------------------------------


@pytest.mark.unit
def test_blob_literal_hex_decodes_to_bytes():
    expr = _e("BLOB 'deadbeef'")
    assert expr == TypedLiteral(TypeTag.Blob, bytes.fromhex("deadbeef"))


@pytest.mark.unit
def test_blob_literal_uppercase_hex():
    expr = _e("BLOB 'DEADBEEF'")
    assert expr.value == b"\xde\xad\xbe\xef"


@pytest.mark.unit
def test_blob_literal_in_insert():
    stmt = _dml("INSERT INTO t (id, data) VALUES (1, BLOB 'cafe')")
    assert stmt.values == ((1, TypedLiteral(TypeTag.Blob, b"\xca\xfe")),)


# --- JSON (REQ-TYP-14) --------------------------------------------------


@pytest.mark.unit
def test_json_literal_object():
    expr = _e("JSON '{\"k\": 1}'")
    assert expr == TypedLiteral(TypeTag.Json, {"k": 1})


@pytest.mark.unit
def test_json_literal_array():
    expr = _e("JSON '[1, 2, 3]'")
    assert expr == TypedLiteral(TypeTag.Json, [1, 2, 3])


@pytest.mark.unit
def test_json_literal_scalar():
    expr = _e("JSON '42'")
    assert expr == TypedLiteral(TypeTag.Json, 42)


@pytest.mark.unit
def test_invalid_json_raises_parse_error():
    with pytest.raises(ParseError):
        _e("JSON '{not valid}'")


# --- mixed / combined ---------------------------------------------------


@pytest.mark.unit
def test_mixed_typed_and_plain_literals_in_insert():
    stmt = _dml(
        "INSERT INTO orders (id, amt, created) "
        "VALUES (1, DECIMAL '9.99', DATETIME '2026-07-09 12:00:00')"
    )
    assert stmt.values == (
        (1, TypedLiteral(TypeTag.Decimal, Decimal("9.99")),
         TypedLiteral(TypeTag.Datetime, datetime.datetime(2026, 7, 9, 12, 0, 0))),
    )


@pytest.mark.unit
def test_typed_literal_in_select_column_list():
    """A typed literal is a valid SELECT expression."""
    stmt = _dml("SELECT DATE '2026-01-01' FROM t")
    assert stmt.columns == (TypedLiteral(TypeTag.Date, datetime.date(2026, 1, 1)),)


# --- negative: keyword reuse as identifier stays rejected ---------------


@pytest.mark.unit
def test_typed_keyword_used_as_identifier_still_rejected():
    """``SELECT DATE FROM t`` — DATE is a keyword, not an identifier here.
    The parser must NOT try to consume it as a typed literal when no
    STRING_LIT follows."""
    with pytest.raises(ParseError):
        _e("DATE FROM")