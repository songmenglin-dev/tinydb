"""Tests for the public exception hierarchy.

T-1.2 covers REQ-SQL-7 (parse error carries line/column) plus the
exception base class used by storage, executor, and transaction layers.
"""

import pytest

import tinydb
from tinydb.errors import (
    ConstraintViolation,
    NotNullViolation,
    ParseError,
    TinydbError,
    TypeMismatchError,
)


# --- base hierarchy --------------------------------------------------------


def test_tinydb_error_is_base():
    assert issubclass(ParseError, TinydbError)
    assert issubclass(ConstraintViolation, TinydbError)
    assert issubclass(NotNullViolation, ConstraintViolation)
    assert issubclass(TypeMismatchError, TinydbError)


def test_tinydb_error_reexported_from_top_level():
    # Public re-exports must work; this is what user code catches.
    assert tinydb.TinydbError is TinydbError
    assert tinydb.ParseError is ParseError
    assert tinydb.ConstraintViolation is ConstraintViolation
    assert tinydb.NotNullViolation is NotNullViolation
    assert tinydb.TypeMismatchError is TypeMismatchError


# --- ParseError carries line / column ------------------------------------


def test_parse_error_stores_line_and_column():
    err = ParseError(line=3, col=12, msg="unexpected token")
    assert err.line == 3
    assert err.col == 12
    assert err.msg == "unexpected token"


def test_parse_error_str_includes_position():
    err = ParseError(line=3, col=12, msg="unexpected token")
    text = str(err)
    assert "3" in text
    assert "12" in text
    assert "unexpected token" in text


def test_parse_error_uses_one_indexed_position():
    # We never pass 0; the convention is 1-based.
    err = ParseError(line=1, col=1, msg="empty input")
    assert err.line == 1
    assert err.col == 1


def test_parse_error_is_catchable_as_tinydb_error():
    with pytest.raises(TinydbError):
        raise ParseError(1, 1, "boom")


# --- ConstraintViolation / NotNullViolation ------------------------------


def test_constraint_violation_carries_message():
    err = ConstraintViolation("UNIQUE violation on column 'email'")
    assert "UNIQUE" in str(err)


def test_not_null_violation_is_a_constraint_violation():
    with pytest.raises(ConstraintViolation):
        raise NotNullViolation("column 'name' cannot be NULL")


def test_type_mismatch_is_catchable_as_tinydb_error():
    with pytest.raises(TinydbError):
        raise TypeMismatchError("expected INT, got TEXT")
