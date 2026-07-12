"""Value coercion: turn a Python value into on-disk bytes for a target column.

The contract is intentionally strict.  Only a small number of
lossless implicit conversions are allowed (see REQ-TYP-6):

* ``int → FLOAT`` is allowed (3 becomes 3.0).
* ``int → DECIMAL`` is allowed.
* ``bool → BOOL`` is allowed; ``int → BOOL`` is **not**.

Anything that could silently change the user's value — fractional
floats becoming ints, strings being parsed as numbers, floats becoming
DECIMALs — is rejected up front.  Callers that want to force a
conversion should do it explicitly in their code, not here.

The function returns ``(encoded_bytes, tag)`` so the caller (storage
or executor) knows both the bytes to write **and** the tag actually
used.  When the widened tag differs from the requested one (e.g.
``int → FLOAT``) the returned tag is the widened one.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any, Sequence

from tinydb.errors import TypeMismatchError
from tinydb.types.codec import encode_value
from tinydb.types.system import TypeTag


# JSON-serialisable scalar/container types we accept.  ``set`` /
# ``frozenset`` are deliberately excluded — round-tripping through a
# list would surprise callers.
_JSON_OK = (type(None), bool, int, float, str, list, dict, tuple)


def coerce_value(value: Any, target_tag: TypeTag) -> tuple[bytes, TypeTag]:
    """Coerce ``value`` to fit ``target_tag`` and return ``(bytes, tag)``.

    Raises :class:`~tinydb.errors.TypeMismatchError` for any disallowed
    conversion.  On success, ``tag`` is the actual :class:`TypeTag`
    used — for the int → FLOAT widening this is :attr:`TypeTag.Float`,
    not :attr:`TypeTag.Int`.
    """
    # --- NULL ------------------------------------------------------------
    if target_tag is TypeTag.Null:
        if value is None:
            return encode_value(None, TypeTag.Null), TypeTag.Null
        raise TypeMismatchError(
            f"NULL column requires None, got {type(value).__name__}"
        )

    if value is None:
        # JSON has its own null literal (distinct from the column-NULL
        # in TypeTag.Null) so JSON columns explicitly accept None.
        if target_tag is TypeTag.Json:
            return encode_value(None, TypeTag.Json), TypeTag.Json
        raise TypeMismatchError(
            f"TypeTag.{target_tag.name} cannot accept None "
            f"(use a NULL-typed column for SQL NULL)"
        )

    # --- INT -------------------------------------------------------------
    if target_tag is TypeTag.Int:
        # bool is a subclass of int in Python; reject it explicitly so
        # BOOL stays distinct.
        if isinstance(value, bool):
            raise TypeMismatchError("INT column does not accept bool")
        if isinstance(value, int):
            return encode_value(value, TypeTag.Int), TypeTag.Int
        if isinstance(value, float):
            if value.is_integer():
                return encode_value(int(value), TypeTag.Int), TypeTag.Int
            raise TypeMismatchError(
                f"INT column cannot accept fractional float {value!r}"
            )
        raise TypeMismatchError(
            f"INT column cannot accept {type(value).__name__}"
        )

    # --- FLOAT -----------------------------------------------------------
    if target_tag is TypeTag.Float:
        if isinstance(value, bool):
            raise TypeMismatchError("FLOAT column does not accept bool")
        if isinstance(value, (int, float)):
            # int → float widening is the one allowed lossless numeric
            # widening.
            return encode_value(float(value), TypeTag.Float), TypeTag.Float
        raise TypeMismatchError(
            f"FLOAT column cannot accept {type(value).__name__}"
        )

    # --- TEXT ------------------------------------------------------------
    if target_tag is TypeTag.Text:
        if isinstance(value, str):
            return encode_value(value, TypeTag.Text), TypeTag.Text
        raise TypeMismatchError(
            f"TEXT column cannot accept {type(value).__name__}"
        )

    # --- BOOL ------------------------------------------------------------
    if target_tag is TypeTag.Bool:
        if isinstance(value, bool):
            return encode_value(value, TypeTag.Bool), TypeTag.Bool
        raise TypeMismatchError(
            f"BOOL column only accepts True / False, got {type(value).__name__}"
        )

    # --- DATE ------------------------------------------------------------
    if target_tag is TypeTag.Date:
        if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
            return encode_value(value, TypeTag.Date), TypeTag.Date
        raise TypeMismatchError(
            f"DATE column cannot accept {type(value).__name__}"
        )

    # --- TIME ------------------------------------------------------------
    if target_tag is TypeTag.Time:
        if isinstance(value, datetime.time):
            return encode_value(value, TypeTag.Time), TypeTag.Time
        raise TypeMismatchError(
            f"TIME column cannot accept {type(value).__name__}"
        )

    # --- DATETIME --------------------------------------------------------
    if target_tag is TypeTag.Datetime:
        if isinstance(value, datetime.datetime):
            return encode_value(value, TypeTag.Datetime), TypeTag.Datetime
        raise TypeMismatchError(
            f"DATETIME column cannot accept {type(value).__name__}"
        )

    # --- DECIMAL ---------------------------------------------------------
    if target_tag is TypeTag.Decimal:
        if isinstance(value, bool):
            raise TypeMismatchError("DECIMAL column does not accept bool")
        if isinstance(value, Decimal):
            return encode_value(value, TypeTag.Decimal), TypeTag.Decimal
        if isinstance(value, int):
            return encode_value(Decimal(value), TypeTag.Decimal), TypeTag.Decimal
        raise TypeMismatchError(
            f"DECIMAL column cannot accept {type(value).__name__} "
            f"(wrap in Decimal() explicitly to avoid float coercion)"
        )

    # --- BLOB ------------------------------------------------------------
    if target_tag is TypeTag.Blob:
        if isinstance(value, (bytes, bytearray)):
            return encode_value(bytes(value), TypeTag.Blob), TypeTag.Blob
        raise TypeMismatchError(
            f"BLOB column cannot accept {type(value).__name__}"
        )

    # --- JSON ------------------------------------------------------------
    if target_tag is TypeTag.Json:
        if not isinstance(value, _JSON_OK):
            raise TypeMismatchError(
                f"JSON column cannot accept {type(value).__name__}"
            )
        if isinstance(value, set) or isinstance(value, frozenset):
            # ``set`` matched the bare ``object`` check above; the
            # ``_JSON_OK`` tuple deliberately excludes it.
            raise TypeMismatchError(
                "JSON column does not accept set (use list explicitly)"
            )
        # ``json.dumps`` validates JSON-serialisability — any leftover
        # unsupported type surfaces here rather than at decode time.
        try:
            json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise TypeMismatchError(
                f"value is not JSON-serialisable: {exc}"
            ) from exc
        return encode_value(value, TypeTag.Json), TypeTag.Json

    raise TypeMismatchError(f"unsupported TypeTag: {target_tag!r}")


__all__ = ["coerce_value"]
