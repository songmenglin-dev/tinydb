"""On-disk value codec.

Every value stored in a tinydb page uses this wire format::

    <1 byte TypeTag>  <payload>

The payload depends on the type:

* **Fixed-size**: ``Int`` (8B signed), ``Float`` (8B IEEE 754),
  ``Bool`` (1B), ``Date`` (4B signed days since 1970-01-01),
  ``Time`` (8B microseconds since midnight), ``Datetime`` (8B
  microseconds since the Unix epoch, UTC).
* **Length-prefixed**: ``Text`` / ``Decimal`` / ``Blob`` / ``Json`` all
  have a 4-byte little-endian length followed by the raw bytes (UTF-8
  for the textual types, base bytes for the binary ones).
* ``Null`` is just the tag byte — the payload is zero bytes.

The codec is intentionally simple: no compression, no varint, no CRC.
Durability is provided by the WAL; per-page checksums can be added
later without breaking the format.
"""

from __future__ import annotations

import datetime
import json
import struct
from decimal import Decimal
from typing import Any, Sequence

from tinydb.types.system import TypeTag

from tinydb.types.system import TypeTag


# Epoch used for DATE / DATETIME encoding.  We deliberately pin this to
# the Unix epoch so the on-disk bytes are unambiguous.
_EPOCH_DATE = datetime.date(1970, 1, 1)

# 4-byte little-endian unsigned length prefix.
_LEN_FMT = "<I"
# 4-byte little-endian signed (used for DATE day-count).
_I32_FMT = "<i"
# 8-byte little-endian signed (used for INT / DATETIME).
_I64_FMT = "<q"
# 8-byte little-endian unsigned (used for TIME microseconds).
_U64_FMT = "<Q"
# 8-byte little-endian double (used for FLOAT).
_D64_FMT = "<d"

_LEN_SIZE = 4
_TAG_SIZE = 1


class _CodecError(TypeError):
    """Raised when the Python value does not fit the requested :class:`TypeTag`."""


def value_size(value: Any, tag: TypeTag) -> int:
    """Return the number of bytes ``encode_value`` will produce.

    This is the on-disk size, including the tag byte.  Useful for
    callers (e.g. the heap) that need to pre-allocate a slot.
    """
    if tag is TypeTag.Null:
        if value is not None:
            raise _CodecError(f"TypeTag.Null requires None, got {type(value).__name__}")
        return _TAG_SIZE
    if value is None:
        # JSON has its own null literal (distinct from tinydb's column-NULL
        # in TypeTag.Null), so the JSON column explicitly accepts None.
        if tag is TypeTag.Json:
            return _TAG_SIZE + _LEN_SIZE + len("null")
        raise _CodecError(f"TypeTag.{tag.name} cannot encode None")
    if tag is TypeTag.Int:
        _check_int_range(value)
        return _TAG_SIZE + 8
    if tag is TypeTag.Float:
        return _TAG_SIZE + 8
    if tag is TypeTag.Bool:
        if not isinstance(value, bool):
            raise _CodecError(f"TypeTag.Bool requires bool, got {type(value).__name__}")
        return _TAG_SIZE + 1
    if tag is TypeTag.Date:
        if not isinstance(value, datetime.date):
            raise _CodecError(f"TypeTag.Date requires datetime.date, got {type(value).__name__}")
        return _TAG_SIZE + 4
    if tag is TypeTag.Time:
        if not isinstance(value, datetime.time):
            raise _CodecError(f"TypeTag.Time requires datetime.time, got {type(value).__name__}")
        return _TAG_SIZE + 8
    if tag is TypeTag.Datetime:
        if not isinstance(value, datetime.datetime):
            raise _CodecError(f"TypeTag.Datetime requires datetime.datetime, got {type(value).__name__}")
        return _TAG_SIZE + 8
    if tag is TypeTag.Text:
        if not isinstance(value, str):
            raise _CodecError(f"TypeTag.Text requires str, got {type(value).__name__}")
        return _TAG_SIZE + _LEN_SIZE + len(value.encode("utf-8"))
    if tag is TypeTag.Decimal:
        if not isinstance(value, Decimal):
            raise _CodecError(f"TypeTag.Decimal requires Decimal, got {type(value).__name__}")
        text = format(value, "f")
        return _TAG_SIZE + _LEN_SIZE + len(text.encode("utf-8"))
    if tag is TypeTag.Blob:
        if not isinstance(value, (bytes, bytearray)):
            raise _CodecError(f"TypeTag.Blob requires bytes, got {type(value).__name__}")
        return _TAG_SIZE + _LEN_SIZE + len(value)
    if tag is TypeTag.Json:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return _TAG_SIZE + _LEN_SIZE + len(text.encode("utf-8"))
    raise _CodecError(f"unsupported TypeTag: {tag!r}")


def encode_value(value: Any, tag: TypeTag) -> bytes:
    """Serialise ``value`` under ``tag`` to bytes."""
    size = value_size(value, tag)  # validates tag/value pairing
    if tag is TypeTag.Null:
        return bytes([tag.value])
    if tag is TypeTag.Int:
        return bytes([tag.value]) + struct.pack(_I64_FMT, value)
    if tag is TypeTag.Float:
        return bytes([tag.value]) + struct.pack(_D64_FMT, value)
    if tag is TypeTag.Bool:
        return bytes([tag.value, 1 if value else 0])
    if tag is TypeTag.Date:
        days = (value - _EPOCH_DATE).days
        return bytes([tag.value]) + struct.pack(_I32_FMT, days)
    if tag is TypeTag.Time:
        micros = (value.hour * 3_600 + value.minute * 60 + value.second) * 1_000_000 + value.microsecond
        return bytes([tag.value]) + struct.pack(_U64_FMT, micros)
    if tag is TypeTag.Datetime:
        # Treat naive datetimes as UTC; aware datetimes are converted
        # to UTC before encoding so the on-disk value is unambiguous.
        if value.tzinfo is None:
            epoch = datetime.datetime(1970, 1, 1)
        else:
            value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            epoch = datetime.datetime(1970, 1, 1)
        micros = int((value - epoch).total_seconds() * 1_000_000)
        return bytes([tag.value]) + struct.pack(_I64_FMT, micros)
    if tag is TypeTag.Text:
        payload = value.encode("utf-8")
        return bytes([tag.value]) + struct.pack(_LEN_FMT, len(payload)) + payload
    if tag is TypeTag.Decimal:
        text = format(value, "f")
        payload = text.encode("utf-8")
        return bytes([tag.value]) + struct.pack(_LEN_FMT, len(payload)) + payload
    if tag is TypeTag.Blob:
        payload = bytes(value)
        return bytes([tag.value]) + struct.pack(_LEN_FMT, len(payload)) + payload
    if tag is TypeTag.Json:
        text = "null" if value is None else json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        )
        payload = text.encode("utf-8")
        return bytes([tag.value]) + struct.pack(_LEN_FMT, len(payload)) + payload
    raise _CodecError(f"unsupported TypeTag: {tag!r}")  # pragma: no cover


def decode_value(buf: bytes, offset: int = 0) -> tuple[Any, int]:
    """Deserialise one value starting at ``offset``.

    Returns ``(value, next_offset)`` where ``next_offset`` is the byte
    position immediately after the consumed value — pass it back in to
    walk a packed buffer field by field.
    """
    if offset >= len(buf):
        raise ValueError("buffer underrun: no tag byte to read")
    tag_byte = buf[offset]
    offset += 1
    try:
        tag = TypeTag(tag_byte)
    except ValueError as exc:
        raise ValueError(f"unknown TypeTag byte: 0x{tag_byte:02x}") from exc

    if tag is TypeTag.Null:
        return None, offset
    if tag is TypeTag.Int:
        (raw,) = struct.unpack_from(_I64_FMT, buf, offset)
        return int(raw), offset + 8
    if tag is TypeTag.Float:
        (raw,) = struct.unpack_from(_D64_FMT, buf, offset)
        return float(raw), offset + 8
    if tag is TypeTag.Bool:
        raw = buf[offset]
        return bool(raw), offset + 1
    if tag is TypeTag.Date:
        (days,) = struct.unpack_from(_I32_FMT, buf, offset)
        return _EPOCH_DATE + datetime.timedelta(days=days), offset + 4
    if tag is TypeTag.Time:
        (micros,) = struct.unpack_from(_U64_FMT, buf, offset)
        seconds, micros = divmod(micros, 1_000_000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return datetime.time(hours, minutes, seconds, micros), offset + 8
    if tag is TypeTag.Datetime:
        (micros,) = struct.unpack_from(_I64_FMT, buf, offset)
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(microseconds=micros), offset + 8
    if tag is TypeTag.Text:
        (length,) = struct.unpack_from(_LEN_FMT, buf, offset)
        offset += _LEN_SIZE
        return buf[offset : offset + length].decode("utf-8"), offset + length
    if tag is TypeTag.Decimal:
        (length,) = struct.unpack_from(_LEN_FMT, buf, offset)
        offset += _LEN_SIZE
        text = buf[offset : offset + length].decode("utf-8")
        return Decimal(text), offset + length
    if tag is TypeTag.Blob:
        (length,) = struct.unpack_from(_LEN_FMT, buf, offset)
        offset += _LEN_SIZE
        return bytes(buf[offset : offset + length]), offset + length
    if tag is TypeTag.Json:
        (length,) = struct.unpack_from(_LEN_FMT, buf, offset)
        offset += _LEN_SIZE
        text = buf[offset : offset + length].decode("utf-8")
        return json.loads(text), offset + length
    raise ValueError(f"unsupported TypeTag: {tag!r}")  # pragma: no cover


def _check_int_range(value: int) -> None:
    """Reject ints outside the int64 envelope that the codec stores."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise _CodecError(f"TypeTag.Int requires int, got {type(value).__name__}")
    if value < -(2**63) or value > 2**63 - 1:
        raise OverflowError(f"int {value} does not fit in signed 64-bit")


def encode_row(values: Sequence[Any], tags: Sequence[TypeTag]) -> bytes:
    """Pack a row as a sequence of length-prefixed values.

    Each value is encoded with ``encode_value(value, tags[i])``. Used by
    the executor when a Heap stores a tuple of column-major encoded
    blobs (REQ-QEX-1).
    """
    if len(values) != len(tags):
        raise ValueError(
            f"encode_row: {len(values)} values vs {len(tags)} tags"
        )
    out = bytearray()
    for v, t in zip(values, tags):
        out += encode_value(v, t)
    return bytes(out)


def decode_row(blob: bytes, tags: Sequence[TypeTag]) -> tuple:
    """Reverse of :func:`encode_row` — returns a tuple of Python values.

    Raises if ``blob`` ends mid-value (defensive: Heap should not produce
    truncated records, but we want a clear error if it does).
    """
    out: list = []
    offset = 0
    for t in tags:
        v, offset = decode_value(blob, offset)
        out.append(v)
    if offset != len(blob):
        raise ValueError(
            f"decode_row: {len(blob) - offset} trailing bytes "
            f"(expected exactly {len(blob)} consumed)"
        )
    return tuple(out)


def encode_row_coerced(
    values: Sequence[Any], tags: Sequence[TypeTag]
) -> bytes:
    """Encode a row by coercing each value to its column's declared tag.

    Used by the executor when writing a row from INSERT or UPDATE: the
    parser hands us raw Python values (already unwrapped from
    ``Literal``), and we apply the per-column coercion rules so
    numeric widening (int → FLOAT), JSON validation, etc. all land in
    the right bytes before they hit the heap.

    NULL special-case: a Python ``None`` into any nullable column is
    encoded as a single ``TypeTag.Null`` byte on disk.  This keeps the
    on-disk representation compact (NULL columns are not the common
    case in v0.1) and lets SELECT decode it back to ``None`` uniformly
    via :func:`decode_value`.  ``coerce_value`` rejects ``None`` for
    any non-JSON/Null tag, so the NULL case is handled here before
    delegating.

    Length of ``values`` and ``tags`` must match; raises
    :class:`ValueError` otherwise (mirrors :func:`encode_row`).
    """
    # Local import: tinydb.types.coerce imports encode_value from this
    # module, so a top-level import would form a cycle.
    from tinydb.types.coerce import coerce_value

    if len(values) != len(tags):
        raise ValueError(
            f"encode_row_coerced: {len(values)} values vs {len(tags)} tags"
        )
    out = bytearray()
    for v, t in zip(values, tags):
        # TypedLiteral unwrap (T-7.2): the parser preserves
        # ``DATE '...'`` / ``DECIMAL '...'`` as TypedLiteral AST nodes in
        # the INSERT VALUES list so the executor can dispatch on the
        # declared target tag.  Unwrap here so the downstream coerce
        # path sees a plain Python value.
        v = getattr(v, "value", v)
        if v is None:
            # TypeTag.Null covers SQL NULL — 1 byte.  The decoder
            # matches this and returns ``None`` back to the caller.
            out += encode_value(None, TypeTag.Null)
            continue
        blob, _actual_tag = coerce_value(v, t)
        out += blob
    return bytes(out)


__all__ = [
    "encode_value",
    "decode_value",
    "value_size",
    "encode_row",
    "decode_row",
    "encode_row_coerced",
]
