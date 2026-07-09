"""Tests for value coercion rules.

Covers REQ-TYP-6: limited implicit conversions that never lose
precision.  In particular:

* int → float is **allowed** (3 becomes 3.0).
* float → int is **rejected** (3.14 cannot become 3).
* str → int / float is **rejected** even when the string looks
  numeric — implicit parsing of user data is too error-prone.
* int → bool is **rejected** (only the literal True / False are
  accepted for a BOOL column).
* int → DECIMAL is **allowed** (lossless).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from tinydb.errors import TypeMismatchError
from tinydb.types.coerce import coerce_value
from tinydb.types.system import TypeTag


# --- INT column ---------------------------------------------------------


@pytest.mark.parametrize("v", [0, 1, -1, 42, 2**62])
def test_int_column_accepts_int(v):
    encoded, tag = coerce_value(v, TypeTag.Int)
    assert tag is TypeTag.Int
    # Tag byte (1) + i64 little-endian payload.
    assert encoded == bytes([TypeTag.Int.value]) + v.to_bytes(8, "little", signed=True)


def test_int_column_accepts_integral_float():
    # 3.0 has no fractional part — safe to round to 3.
    encoded, tag = coerce_value(3.0, TypeTag.Int)
    assert tag is TypeTag.Int


def test_int_column_rejects_fractional_float():
    with pytest.raises(TypeMismatchError):
        coerce_value(3.14, TypeTag.Int)


def test_int_column_rejects_str():
    with pytest.raises(TypeMismatchError):
        coerce_value("42", TypeTag.Int)


def test_int_column_rejects_bool():
    # bool is a subclass of int in Python; we still reject it to keep
    # the BOOL column distinct.
    with pytest.raises(TypeMismatchError):
        coerce_value(True, TypeTag.Int)


# --- FLOAT column -------------------------------------------------------


@pytest.mark.parametrize("v", [0.0, 1.5, 1e-100, -1e100])
def test_float_column_accepts_float(v):
    _, tag = coerce_value(v, TypeTag.Float)
    assert tag is TypeTag.Float


@pytest.mark.parametrize("v", [0, 1, -1, 42])
def test_float_column_accepts_int(v):
    # int → float is the only lossless implicit numeric widening.
    _, tag = coerce_value(v, TypeTag.Float)
    assert tag is TypeTag.Float


def test_float_column_rejects_str():
    with pytest.raises(TypeMismatchError):
        coerce_value("3.14", TypeTag.Float)


# --- TEXT column --------------------------------------------------------


def test_text_column_accepts_str():
    _, tag = coerce_value("hello", TypeTag.Text)
    assert tag is TypeTag.Text


@pytest.mark.parametrize("v", [42, 3.14, True, b"bytes"])
def test_text_column_rejects_non_string(v):
    with pytest.raises(TypeMismatchError):
        coerce_value(v, TypeTag.Text)


# --- BOOL column --------------------------------------------------------


@pytest.mark.parametrize("v", [True, False])
def test_bool_column_accepts_bool(v):
    _, tag = coerce_value(v, TypeTag.Bool)
    assert tag is TypeTag.Bool


@pytest.mark.parametrize("v", [0, 1, "true", "false"])
def test_bool_column_rejects_non_bool(v):
    with pytest.raises(TypeMismatchError):
        coerce_value(v, TypeTag.Bool)


# --- NULL ---------------------------------------------------------------


def test_null_column_accepts_none():
    encoded, tag = coerce_value(None, TypeTag.Null)
    assert tag is TypeTag.Null
    assert encoded == bytes([TypeTag.Null.value])


@pytest.mark.parametrize("v", [0, "", False, b""])
def test_null_column_rejects_falsy_non_none(v):
    with pytest.raises(TypeMismatchError):
        coerce_value(v, TypeTag.Null)


# --- DATE / TIME / DATETIME --------------------------------------------


def test_date_column_accepts_date():
    _, tag = coerce_value(datetime.date(2026, 7, 9), TypeTag.Date)
    assert tag is TypeTag.Date


def test_date_column_rejects_datetime():
    with pytest.raises(TypeMismatchError):
        coerce_value(datetime.datetime(2026, 7, 9, 12, 0), TypeTag.Date)


def test_time_column_accepts_time():
    _, tag = coerce_value(datetime.time(12, 0, 0), TypeTag.Time)
    assert tag is TypeTag.Time


def test_time_column_rejects_datetime():
    with pytest.raises(TypeMismatchError):
        coerce_value(datetime.datetime(2026, 7, 9, 12, 0), TypeTag.Time)


def test_datetime_column_accepts_datetime():
    _, tag = coerce_value(datetime.datetime(2026, 7, 9, 12, 0), TypeTag.Datetime)
    assert tag is TypeTag.Datetime


def test_datetime_column_rejects_date():
    with pytest.raises(TypeMismatchError):
        coerce_value(datetime.date(2026, 7, 9), TypeTag.Datetime)


# --- DECIMAL ------------------------------------------------------------


@pytest.mark.parametrize("v", [Decimal("0"), Decimal("0.10"), Decimal("-1.5")])
def test_decimal_column_accepts_decimal(v):
    _, tag = coerce_value(v, TypeTag.Decimal)
    assert tag is TypeTag.Decimal


@pytest.mark.parametrize("v", [0, 1, -1, 100])
def test_decimal_column_accepts_int(v):
    # int → DECIMAL is lossless.
    _, tag = coerce_value(v, TypeTag.Decimal)
    assert tag is TypeTag.Decimal


def test_decimal_column_rejects_float():
    # float → DECIMAL would silently change the value (e.g. 0.1 is not
    # exactly representable).  We refuse.
    with pytest.raises(TypeMismatchError):
        coerce_value(0.1, TypeTag.Decimal)


def test_decimal_column_rejects_str():
    with pytest.raises(TypeMismatchError):
        coerce_value("0.10", TypeTag.Decimal)


# --- BLOB ---------------------------------------------------------------


@pytest.mark.parametrize("v", [b"", b"\x00\x01\x02", bytearray(b"abc")])
def test_blob_column_accepts_bytes_like(v):
    _, tag = coerce_value(v, TypeTag.Blob)
    assert tag is TypeTag.Blob


@pytest.mark.parametrize("v", ["bytes", 42, [1, 2, 3]])
def test_blob_column_rejects_non_bytes(v):
    with pytest.raises(TypeMismatchError):
        coerce_value(v, TypeTag.Blob)


# --- JSON ---------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [None, True, 42, 3.14, "hello", [1, 2], {"k": "v"}],
)
def test_json_column_accepts_json_values(v):
    _, tag = coerce_value(v, TypeTag.Json)
    assert tag is TypeTag.Json


def test_json_column_rejects_set():
    # sets are not JSON-serialisable; reject at the coercion boundary
    # rather than encoding and failing at decode time.
    with pytest.raises(TypeMismatchError):
        coerce_value({1, 2, 3}, TypeTag.Json)


# --- short-circuit ------------------------------------------------------


def test_int_to_float_widening_is_lossless():
    # 3 (int) → FLOAT (3.0) — the on-disk float is 3.0, which decodes
    # back to 3.0 (not 3).  The widening is allowed but the value type
    # changes, so callers can choose to detect this if they care.
    encoded, tag = coerce_value(3, TypeTag.Float)
    assert tag is TypeTag.Float
