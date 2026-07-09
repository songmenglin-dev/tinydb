"""Tests for the value codec (encode / decode round-trip).

Covers REQ-TYP-1 ~ REQ-TYP-5 and REQ-TYP-9 ~ REQ-TYP-14 by verifying
that every supported type survives an encode / decode round-trip with
the on-disk wire format:

    <1B TypeTag> <length-prefix?> <payload>

INT / FLOAT / BOOL / DATE / TIME / DATETIME use a fixed-size payload.
TEXT / DECIMAL / BLOB / JSON use a 4-byte little-endian length prefix.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest

from tinydb.types.codec import decode_value, encode_value, value_size
from tinydb.types.system import TypeTag


# --- INT ----------------------------------------------------------------


@pytest.mark.parametrize("v", [0, 1, -1, 42, -42, 2**62, -(2**62), 2**63 - 1, -(2**63)])
def test_int_roundtrip(v):
    buf = encode_value(v, TypeTag.Int)
    assert value_size(v, TypeTag.Int) == len(buf)
    decoded, offset = decode_value(buf)
    assert offset == len(buf)
    assert decoded == v
    assert isinstance(decoded, int)


def test_int_overflow_rejected():
    with pytest.raises(OverflowError):
        encode_value(2**63, TypeTag.Int)
    with pytest.raises(OverflowError):
        encode_value(-(2**63) - 1, TypeTag.Int)


# --- FLOAT --------------------------------------------------------------


@pytest.mark.parametrize("v", [0.0, 1.5, -1.5, 1e-100, 1e100, -1e-100, 3.141592653589793])
def test_float_roundtrip(v):
    buf = encode_value(v, TypeTag.Float)
    assert value_size(v, TypeTag.Float) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, float)


# --- TEXT ---------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        "",
        "hello",
        "hello, 世界",  # multibyte
        "x" * 1024,
        "with\nnewlines\tand\ttabs",
    ],
)
def test_text_roundtrip(v):
    buf = encode_value(v, TypeTag.Text)
    assert value_size(v, TypeTag.Text) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, str)


# --- BOOL ---------------------------------------------------------------


@pytest.mark.parametrize("v", [True, False])
def test_bool_roundtrip(v):
    buf = encode_value(v, TypeTag.Bool)
    assert value_size(v, TypeTag.Bool) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded is v
    assert isinstance(decoded, bool)


# --- DATE ---------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        datetime.date(1970, 1, 1),
        datetime.date(2026, 7, 9),
        datetime.date(1900, 1, 1),
        datetime.date(2100, 12, 31),
    ],
)
def test_date_roundtrip(v):
    buf = encode_value(v, TypeTag.Date)
    assert value_size(v, TypeTag.Date) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, datetime.date)


# --- TIME ---------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        datetime.time(0, 0, 0),
        datetime.time(14, 30, 0),
        datetime.time(23, 59, 59, 999_999),
    ],
)
def test_time_roundtrip(v):
    buf = encode_value(v, TypeTag.Time)
    assert value_size(v, TypeTag.Time) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, datetime.time)


# --- DATETIME -----------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        datetime.datetime(1970, 1, 1, 0, 0, 0),
        datetime.datetime(2026, 7, 9, 14, 30, 0),
        datetime.datetime(1900, 1, 1, 0, 0, 0),
        datetime.datetime(2100, 12, 31, 23, 59, 59),
    ],
)
def test_datetime_roundtrip(v):
    buf = encode_value(v, TypeTag.Datetime)
    assert value_size(v, TypeTag.Datetime) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, datetime.datetime)


# --- DECIMAL ------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        Decimal("0"),
        Decimal("0.10"),  # exact, not 0.1
        Decimal("-1234.5678"),
        Decimal("12345678901234567890.0987654321"),
    ],
)
def test_decimal_roundtrip(v):
    buf = encode_value(v, TypeTag.Decimal)
    assert value_size(v, TypeTag.Decimal) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, Decimal)


# --- BLOB ---------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        b"",
        b"\x00",
        bytes(range(256)),
        b"binary \x00 data \xff",
    ],
)
def test_blob_roundtrip(v):
    buf = encode_value(v, TypeTag.Blob)
    assert value_size(v, TypeTag.Blob) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, bytes)


# --- JSON ---------------------------------------------------------------


@pytest.mark.parametrize(
    "v",
    [
        None,
        True,
        42,
        "hello",
        [1, 2, 3],
        {"k": "v", "n": 1},
        {"nested": {"a": [1, 2, {"b": None}]}},
    ],
)
def test_json_roundtrip(v):
    buf = encode_value(v, TypeTag.Json)
    decoded, _ = decode_value(buf)
    # JSON round-trips: numbers stay as int/float; bool/None stay.
    assert decoded == v


# --- NULL handling ------------------------------------------------------


def test_encode_value_rejects_none_without_null_tag():
    # `None` is only legal for TypeTag.Null; for any other tag it is a
    # programming error.
    with pytest.raises(TypeError):
        encode_value(None, TypeTag.Int)


def test_null_is_a_valid_tag_with_no_payload():
    # Encoding `None` against TypeTag.Null returns just the tag byte;
    # decoding it yields (None, 1).
    buf = encode_value(None, TypeTag.Null)
    assert buf == bytes([TypeTag.Null.value])
    assert value_size(None, TypeTag.Null) == 1
    decoded, offset = decode_value(buf)
    assert decoded is None
    assert offset == 1


# --- wrong tag for value type -------------------------------------------


def test_encode_value_rejects_str_against_int_tag():
    with pytest.raises(TypeError):
        encode_value("42", TypeTag.Int)


def test_encode_value_rejects_int_against_text_tag():
    with pytest.raises(TypeError):
        encode_value(42, TypeTag.Text)


# --- decoding walks offsets correctly ------------------------------------


def test_decode_value_with_explicit_offset():
    a = encode_value(7, TypeTag.Int)
    b = encode_value("hi", TypeTag.Text)
    buf = a + b
    v1, off1 = decode_value(buf, offset=0)
    v2, off2 = decode_value(buf, offset=off1)
    assert v1 == 7
    assert v2 == "hi"
    assert off2 == len(buf)
