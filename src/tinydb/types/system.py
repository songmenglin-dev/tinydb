"""Type-system primitives: the on-disk type tag and the column descriptor.

These are the foundations every other layer (codec, storage, executor,
type checker) sits on.  They have **no** I/O and **no** dependencies on
the rest of the package, so they can be unit-tested in isolation.

TypeTag
-------

The ``TypeTag`` enum assigns a single byte to every supported column
type.  Using a byte — not a Python string or class object — means a
column's type can be written into a page without further encoding and
read back by looking at exactly one byte.

* ``Null = 0x00`` is reserved as the "no value" sentinel so a
  freshly-allocated byte defaults to NULL.
* The remaining tags are in the ``0x01..0x0A`` range; values above
  ``0x0A`` are reserved for future use and must be rejected on read.

Column
------

``Column`` is a frozen dataclass: once a table is created its schema
must not change shape.  Mutating a column would invalidate every page
that referenced the old layout.

parse_type_name
---------------

Maps SQL type names (which are plentiful and case-insensitive —
``INTEGER`` / ``INT`` / ``int`` are all the same) onto the canonical
:class:`TypeTag`.  The parser feeds this; new aliases are added in one
place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TypeTag(Enum):
    """On-disk type tag written as a single byte before each value."""

    # 0x00 is reserved for "no value" / uninitialised byte.
    Null = 0x00
    Int = 0x01
    Float = 0x02
    Text = 0x03
    Bool = 0x04
    Date = 0x05
    Time = 0x06
    Datetime = 0x07
    Decimal = 0x08
    Blob = 0x09
    Json = 0x0A


@dataclass(frozen=True)
class Column:
    """Schema descriptor for a single column.

    Frozen because the layout is committed to disk at ``CREATE TABLE``
    time; later mutations would silently corrupt pages written under the
    old layout.
    """

    name: str
    tag: TypeTag
    not_null: bool = False
    primary_key: bool = False
    unique: bool = False


# SQL alias → canonical TypeTag.  Lower-cased keys; lookup is
# case-insensitive and whitespace-stripped.
_TYPE_ALIASES: dict[str, TypeTag] = {
    # integer family
    "int": TypeTag.Int,
    "integer": TypeTag.Int,
    # floating-point family
    "float": TypeTag.Float,
    "double": TypeTag.Float,
    "real": TypeTag.Float,
    # text family
    "text": TypeTag.Text,
    "varchar": TypeTag.Text,
    # boolean
    "bool": TypeTag.Bool,
    "boolean": TypeTag.Bool,
    # date / time
    "date": TypeTag.Date,
    "time": TypeTag.Time,
    "datetime": TypeTag.Datetime,
    "timestamp": TypeTag.Datetime,
    # exact decimal
    "decimal": TypeTag.Decimal,
    "numeric": TypeTag.Decimal,
    # binary
    "blob": TypeTag.Blob,
    "bytea": TypeTag.Blob,
    # structured
    "json": TypeTag.Json,
}


def parse_type_name(raw: str) -> TypeTag:
    """Resolve a SQL type name to its :class:`TypeTag`.

    Whitespace is stripped and the lookup is case-insensitive so
    ``"Int"`` and ``"INT"`` both work.  Unknown names raise
    :class:`ValueError`; the parser is expected to catch and re-raise
    as :class:`~tinydb.errors.ParseError` with the offending token's
    position.
    """
    key = raw.strip().lower()
    try:
        return _TYPE_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"unknown SQL type: {raw!r}") from exc


__all__ = ["TypeTag", "Column", "parse_type_name"]
