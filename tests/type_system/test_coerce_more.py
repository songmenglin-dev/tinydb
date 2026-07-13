"""Extra coercion tests — strict-mode error paths and widening.

Complements :mod:`tests.type_system.test_coerce`.  Targets the branches
that the round-trip suite leaves untouched: bool-vs-int, NULL into
typed columns, JSON with sets/non-serialisable values, decimal from
int widening, blob from bytearray, and the ``unsupported TypeTag``
defensive branch.
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest

from tinydb.errors import TypeMismatchError
from tinydb.types.coerce import coerce_value
from tinydb.types.system import TypeTag


# ---------------------------------------------------------------------------
# INT
# ---------------------------------------------------------------------------
def test_int_accepts_zero_and_negative():
    blob, tag = coerce_value(0, TypeTag.Int)
    assert tag is TypeTag.Int
    assert blob[0] == TypeTag.Int.value


def test_int_accepts_large_value():
    coerce_value(2**62, TypeTag.Int)


def test_int_rejects_bool():
    with pytest.raises(TypeMismatchError):
        coerce_value(True, TypeTag.Int)


def test_int_rejects_fractional_float():
    with pytest.raises(TypeMismatchError):
        coerce_value(3.14, TypeTag.Int)


def test_int_accepts_integer_float():
    blob, tag = coerce_value(7.0, TypeTag.Int)
    assert tag is TypeTag.Int
    assert blob[0] == TypeTag.Int.value


def test_int_rejects_string():
    with pytest.raises(TypeMismatchError):
        coerce_value("42", TypeTag.Int)


# ---------------------------------------------------------------------------
# FLOAT
# ---------------------------------------------------------------------------
def test_float_accepts_int_widening():
    blob, tag = coerce_value(3, TypeTag.Float)
    assert tag is TypeTag.Float
    assert blob[0] == TypeTag.Float.value


def test_float_rejects_bool():
    with pytest.raises(TypeMismatchError):
        coerce_value(True, TypeTag.Float)


def test_float_rejects_string():
    with pytest.raises(TypeMismatchError):
        coerce_value("1.5", TypeTag.Float)


# ---------------------------------------------------------------------------
# TEXT
# ---------------------------------------------------------------------------
def test_text_accepts_empty_string():
    coerce_value("", TypeTag.Text)


def test_text_rejects_int():
    with pytest.raises(TypeMismatchError):
        coerce_value(42, TypeTag.Text)


def test_text_rejects_bool():
    with pytest.raises(TypeMismatchError):
        coerce_value(True, TypeTag.Text)


# ---------------------------------------------------------------------------
# BOOL — strict
# ---------------------------------------------------------------------------
def test_bool_rejects_int():
    with pytest.raises(TypeMismatchError):
        coerce_value(1, TypeTag.Bool)


def test_bool_rejects_string():
    with pytest.raises(TypeMismatchError):
        coerce_value("true", TypeTag.Bool)


# ---------------------------------------------------------------------------
# NULL
# ---------------------------------------------------------------------------
def test_null_column_rejects_non_none():
    with pytest.raises(TypeMismatchError):
        coerce_value(0, TypeTag.Null)


def test_null_column_accepts_none():
    blob, tag = coerce_value(None, TypeTag.Null)
    assert tag is TypeTag.Null


def test_non_null_column_rejects_none():
    with pytest.raises(TypeMismatchError):
        coerce_value(None, TypeTag.Int)


def test_json_column_accepts_none():
    """JSON has its own null literal (distinct from TypeTag.Null)."""
    blob, tag = coerce_value(None, TypeTag.Json)
    assert tag is TypeTag.Json
    # The payload must contain the JSON literal "null".
    assert b"null" in blob


# ---------------------------------------------------------------------------
# DATE / TIME / DATETIME
# ---------------------------------------------------------------------------
def test_date_rejects_datetime_subclass():
    """datetime is a date subclass but DATE is date-only."""
    with pytest.raises(TypeMismatchError):
        coerce_value(datetime.datetime(2026, 7, 9), TypeTag.Date)


def test_time_rejects_string():
    with pytest.raises(TypeMismatchError):
        coerce_value("12:34", TypeTag.Time)


def test_datetime_rejects_date():
    with pytest.raises(TypeMismatchError):
        coerce_value(datetime.date(2026, 7, 9), TypeTag.Datetime)


# ---------------------------------------------------------------------------
# DECIMAL — allow int widening, reject float
# ---------------------------------------------------------------------------
def test_decimal_accepts_int_widening():
    blob, tag = coerce_value(42, TypeTag.Decimal)
    assert tag is TypeTag.Decimal


def test_decimal_rejects_float():
    """Floats are NOT widened into Decimal (would silently lose precision)."""
    with pytest.raises(TypeMismatchError):
        coerce_value(3.14, TypeTag.Decimal)


def test_decimal_rejects_bool():
    with pytest.raises(TypeMismatchError):
        coerce_value(True, TypeTag.Decimal)


def test_decimal_rejects_string():
    with pytest.raises(TypeMismatchError):
        coerce_value("3.14", TypeTag.Decimal)


# ---------------------------------------------------------------------------
# BLOB — bytearray allowed
# ---------------------------------------------------------------------------
def test_blob_accepts_bytearray():
    blob, tag = coerce_value(bytearray(b"\x01\x02"), TypeTag.Blob)
    assert tag is TypeTag.Blob


def test_blob_rejects_string():
    with pytest.raises(TypeMismatchError):
        coerce_value("not bytes", TypeTag.Blob)


# ---------------------------------------------------------------------------
# JSON — set / frozenset rejected, non-serialisable raises
# ---------------------------------------------------------------------------
def test_json_accepts_dict():
    blob, tag = coerce_value({"a": 1}, TypeTag.Json)
    assert tag is TypeTag.Json


def test_json_accepts_list():
    coerce_value([1, 2, 3], TypeTag.Json)


def test_json_rejects_set():
    with pytest.raises(TypeMismatchError):
        coerce_value({1, 2, 3}, TypeTag.Json)


def test_json_rejects_frozenset():
    with pytest.raises(TypeMismatchError):
        coerce_value(frozenset((1, 2)), TypeTag.Json)


def test_json_rejects_non_serialisable():
    class NotSerializable:
        pass

    with pytest.raises(TypeMismatchError):
        coerce_value(NotSerializable(), TypeTag.Json)


def test_json_accepts_nested_structures():
    v = {"a": [1, 2, {"b": None}], "c": True}
    blob, tag = coerce_value(v, TypeTag.Json)
    assert tag is TypeTag.Json
    # Round-trip through json.loads to confirm validity.
    payload = blob[5:]  # strip 1B tag + 4B length prefix
    assert json.loads(payload.decode("utf-8")) == v


# ---------------------------------------------------------------------------
# Tag return value: widening int→FLOAT
# ---------------------------------------------------------------------------
def test_int_to_float_returns_float_tag():
    """The returned tag is the *actual* tag after widening."""
    blob, tag = coerce_value(5, TypeTag.Float)
    assert tag is TypeTag.Float


def test_int_to_decimal_returns_decimal_tag():
    blob, tag = coerce_value(5, TypeTag.Decimal)
    assert tag is TypeTag.Decimal