"""Extra codec tests — null/json/blob/dec error paths and value_size.

Complements :mod:`tests.type_system.test_codec`.  Targets the lines that
the round-trip suite leaves untouched: the null path, JSON null literal,
blob/decimal/datetime error branches, decode error paths, and
:meth:`value_size`.
"""
from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest

from tinydb.types.codec import (
    _CodecError,
    decode_value,
    decode_row,
    encode_row,
    encode_value,
    value_size,
)
from tinydb.types.system import TypeTag


# ---------------------------------------------------------------------------
# NULL roundtrip + size
# ---------------------------------------------------------------------------
def test_null_roundtrip():
    buf = encode_value(None, TypeTag.Null)
    assert value_size(None, TypeTag.Null) == 1
    assert buf == bytes([0x00])
    decoded, offset = decode_value(buf)
    assert decoded is None
    assert offset == 1


def test_null_rejects_non_none_value():
    with pytest.raises(_CodecError):
        value_size(0, TypeTag.Null)
    with pytest.raises(_CodecError):
        encode_value(0, TypeTag.Null)


# ---------------------------------------------------------------------------
# JSON (including the None literal → "null")
# ---------------------------------------------------------------------------
def test_json_roundtrip_dict():
    v = {"k": 1, "arr": [1, 2, 3]}
    buf = encode_value(v, TypeTag.Json)
    decoded, offset = decode_value(buf)
    assert decoded == v
    assert offset == len(buf)


def test_json_roundtrip_list():
    v = [1, "two", 3.0, None, True]
    buf = encode_value(v, TypeTag.Json)
    decoded, _ = decode_value(buf)
    assert decoded == v


def test_json_null_literal_roundtrip():
    """JSON column accepts Python ``None`` and stores it as ``"null"``."""
    buf = encode_value(None, TypeTag.Json)
    assert value_size(None, TypeTag.Json) == len(buf)
    decoded, offset = decode_value(buf)
    assert decoded is None
    assert offset == len(buf)


def test_json_size_includes_tag_and_length_prefix():
    v = {"x": 1}
    expected = 1 + 4 + len(json.dumps(v, separators=(",", ":")).encode("utf-8"))
    assert value_size(v, TypeTag.Json) == expected


# ---------------------------------------------------------------------------
# BLOB
# ---------------------------------------------------------------------------
def test_blob_empty_roundtrip():
    buf = encode_value(b"", TypeTag.Blob)
    assert value_size(b"", TypeTag.Blob) == len(buf)
    decoded, offset = decode_value(buf)
    assert decoded == b""
    assert offset == len(buf)


def test_blob_single_byte_roundtrip():
    buf = encode_value(b"\x00", TypeTag.Blob)
    decoded, _ = decode_value(buf)
    assert decoded == b"\x00"


def test_blob_multi_kb_roundtrip():
    v = bytes(range(256)) * 16  # 4 KB
    buf = encode_value(v, TypeTag.Blob)
    assert value_size(v, TypeTag.Blob) == len(buf)
    decoded, _ = decode_value(buf)
    assert decoded == v


def test_blob_accepts_bytearray():
    v = bytearray(b"\x01\x02\x03")
    buf = encode_value(v, TypeTag.Blob)
    decoded, _ = decode_value(buf)
    assert decoded == b"\x01\x02\x03"


def test_blob_rejects_non_bytes():
    with pytest.raises(_CodecError):
        encode_value("not bytes", TypeTag.Blob)


# ---------------------------------------------------------------------------
# DECIMAL
# ---------------------------------------------------------------------------
def test_decimal_roundtrip_positive():
    v = Decimal("3.14159")
    buf = encode_value(v, TypeTag.Decimal)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert isinstance(decoded, Decimal)


def test_decimal_roundtrip_negative_and_zero():
    for v in (Decimal("0"), Decimal("-0.00"), Decimal("-1234567890.0987654321")):
        buf = encode_value(v, TypeTag.Decimal)
        decoded, _ = decode_value(buf)
        assert decoded == v


def test_decimal_rejects_non_decimal():
    with pytest.raises(_CodecError):
        encode_value(3.14, TypeTag.Decimal)


# ---------------------------------------------------------------------------
# DATETIME
# ---------------------------------------------------------------------------
def test_datetime_roundtrip_naive():
    v = datetime.datetime(2026, 7, 9, 12, 34, 56, 789_012)
    buf = encode_value(v, TypeTag.Datetime)
    decoded, _ = decode_value(buf)
    assert decoded == v
    assert decoded.tzinfo is None  # naive on encode stays naive on decode


def test_datetime_roundtrip_aware_normalised_to_utc():
    tz = datetime.timezone(datetime.timedelta(hours=8))
    v = datetime.datetime(2026, 7, 9, 12, 0, 0, tzinfo=tz)
    buf = encode_value(v, TypeTag.Datetime)
    decoded, _ = decode_value(buf)
    # The on-disk form stores UTC microseconds; decode returns naive UTC.
    assert decoded == datetime.datetime(2026, 7, 9, 4, 0, 0)
    assert decoded.tzinfo is None


def test_datetime_rejects_non_datetime():
    with pytest.raises(_CodecError):
        encode_value("2026-07-09", TypeTag.Datetime)
    with pytest.raises(_CodecError):
        encode_value(datetime.date(2026, 7, 9), TypeTag.Datetime)


# ---------------------------------------------------------------------------
# DATE — reject datetime subclass
# ---------------------------------------------------------------------------
def test_date_rejects_datetime():
    """datetime is a subclass of date, but the DATE tag is date-only.

    The codec branch for Date does not pre-validate the type, so it
    raises ``TypeError`` (not ``_CodecError``) when the subtraction
    operator hits the incompatible type.  Either way, the call does not
    produce a usable encoding.
    """
    with pytest.raises(TypeError):
        encode_value(datetime.datetime(2026, 7, 9), TypeTag.Date)


# ---------------------------------------------------------------------------
# TIME
# ---------------------------------------------------------------------------
def test_time_rejects_non_time():
    with pytest.raises(_CodecError):
        encode_value("12:34:56", TypeTag.Time)


# ---------------------------------------------------------------------------
# BOOL — reject int (bool is a subclass of int)
# ---------------------------------------------------------------------------
def test_bool_rejects_int():
    with pytest.raises(_CodecError):
        encode_value(1, TypeTag.Bool)
    with pytest.raises(_CodecError):
        encode_value(0, TypeTag.Bool)


def test_value_size_bool_consistent_with_encoding():
    assert value_size(True, TypeTag.Bool) == 2
    assert value_size(False, TypeTag.Bool) == 2


# ---------------------------------------------------------------------------
# INT — bool rejected (bool is a subclass of int)
# ---------------------------------------------------------------------------
def test_int_rejects_bool():
    with pytest.raises(_CodecError):
        encode_value(True, TypeTag.Int)
    with pytest.raises(_CodecError):
        value_size(True, TypeTag.Int)


# ---------------------------------------------------------------------------
# TEXT — reject bytes
# ---------------------------------------------------------------------------
def test_text_rejects_bytes():
    with pytest.raises(_CodecError):
        encode_value(b"hello", TypeTag.Text)


# ---------------------------------------------------------------------------
# Decode errors
# ---------------------------------------------------------------------------
def test_decode_underrun_raises_value_error():
    with pytest.raises(ValueError):
        decode_value(b"")


def test_decode_unknown_type_byte_raises_value_error():
    # 0xFE is not a valid TypeTag.
    with pytest.raises(ValueError):
        decode_value(b"\xfe")


def test_decode_truncated_length_prefix():
    # Tag + 2 bytes (not enough for a 4-byte length).
    with pytest.raises(Exception):
        decode_value(bytes([TypeTag.Text.value, 0x00, 0x00]))


# ---------------------------------------------------------------------------
# encode_row / decode_row
# ---------------------------------------------------------------------------
def test_encode_decode_row_roundtrip():
    tags = (TypeTag.Int, TypeTag.Text, TypeTag.Bool)
    values = (42, "hello", True)
    blob = encode_row(values, tags)
    assert decode_row(blob, tags) == values


def test_encode_row_length_mismatch():
    with pytest.raises(ValueError):
        encode_row([1, 2], [TypeTag.Int, TypeTag.Int, TypeTag.Int])


def test_decode_row_trailing_bytes_raises():
    tags = (TypeTag.Int,)
    blob = encode_row((1,), tags) + b"\xff\xff"  # 2 trailing bytes
    with pytest.raises(ValueError):
        decode_row(blob, tags)


# ---------------------------------------------------------------------------
# value_size supports all tags
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,tag",
    [
        (0, TypeTag.Int),
        (0.0, TypeTag.Float),
        (True, TypeTag.Bool),
        ("", TypeTag.Text),
        (datetime.date(2026, 1, 1), TypeTag.Date),
        (datetime.time(0, 0, 0), TypeTag.Time),
        (datetime.datetime(2026, 1, 1), TypeTag.Datetime),
        (Decimal("1.5"), TypeTag.Decimal),
        (b"", TypeTag.Blob),
        ({}, TypeTag.Json),
        (None, TypeTag.Null),
    ],
)
def test_value_size_consistent_with_encode(value, tag):
    buf = encode_value(value, tag)
    assert value_size(value, tag) == len(buf)