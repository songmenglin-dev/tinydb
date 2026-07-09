"""Tests for the type-system primitives (TypeTag + Column).

Covers REQ-TYP-1 ~ REQ-TYP-14, REQ-TYP-8 (types persist in schema) and
the type-name parser used by the SQL ``CREATE TABLE`` statement.
"""

import pytest

from tinydb.types.system import Column, TypeTag, parse_type_name


# --- TypeTag enum ---------------------------------------------------------


def test_type_tag_has_all_eleven_members():
    members = {t.name for t in TypeTag}
    # 10 column types + NULL
    assert members == {
        "Null",
        "Int",
        "Float",
        "Text",
        "Bool",
        "Date",
        "Time",
        "Datetime",
        "Decimal",
        "Blob",
        "Json",
    }


def test_type_tag_values_are_unique():
    values = [t.value for t in TypeTag]
    assert len(values) == len(set(values))


def test_type_tag_null_is_zero():
    # NULL uses 0x00 so an uninitialised byte defaults to NULL — handy
    # for free-space pages and tombstones.
    assert TypeTag.Null.value == 0x00


def test_type_tag_int_is_small_positive():
    # 1-byte tag; we keep values low so the tag byte is easy to spot in
    # hex dumps.
    assert 0 < TypeTag.Int.value < 0x10


# --- Column dataclass -----------------------------------------------------


def test_column_minimal_construction():
    col = Column("age", TypeTag.Int)
    assert col.name == "age"
    assert col.tag is TypeTag.Int
    assert col.not_null is False
    assert col.primary_key is False
    assert col.unique is False


def test_column_with_all_flags():
    col = Column(
        "id", TypeTag.Int, not_null=True, primary_key=True, unique=True
    )
    assert col.not_null is True
    assert col.primary_key is True
    assert col.unique is True


def test_column_immutable_in_shape():
    # Columns are the unit of schema persistence.  They should not be
    # silently mutated after creation; making them a frozen dataclass
    # ensures that contract.
    col = Column("id", TypeTag.Int, primary_key=True)
    with pytest.raises((AttributeError, TypeError)):
        col.name = "other"  # type: ignore[misc]


# --- parse_type_name -----------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("INT", TypeTag.Int),
        ("INTEGER", TypeTag.Int),
        ("int", TypeTag.Int),
        ("FLOAT", TypeTag.Float),
        ("DOUBLE", TypeTag.Float),
        ("REAL", TypeTag.Float),
        ("TEXT", TypeTag.Text),
        ("VARCHAR", TypeTag.Text),
        ("BOOL", TypeTag.Bool),
        ("BOOLEAN", TypeTag.Bool),
        ("DATE", TypeTag.Date),
        ("TIME", TypeTag.Time),
        ("DATETIME", TypeTag.Datetime),
        ("TIMESTAMP", TypeTag.Datetime),
        ("DECIMAL", TypeTag.Decimal),
        ("NUMERIC", TypeTag.Decimal),
        ("BLOB", TypeTag.Blob),
        ("BYTEA", TypeTag.Blob),
        ("JSON", TypeTag.Json),
    ],
)
def test_parse_type_name_aliases(raw, expected):
    assert parse_type_name(raw) is expected


def test_parse_type_name_rejects_unknown():
    with pytest.raises(ValueError):
        parse_type_name("UUID")


def test_parse_type_name_strips_whitespace():
    assert parse_type_name("  INT  ") is TypeTag.Int
