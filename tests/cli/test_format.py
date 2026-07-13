"""Tests for tinydb.cli.format — Result table formatter (T-8.2).

Covers:
1. Empty rows -> "".
2. Single row, single column -> header + value.
3. Multi-row, multi-column -> aligned columns.
4. Long values expand column width (no truncation in v0.1).
5. Header auto-generated when columns=None.
6. Header custom when columns=[...] is supplied.
7. Numeric vs string cells render correctly.
"""
from __future__ import annotations

from tinydb.cli.format import format_rows


def test_empty_rows_returns_empty_string() -> None:
    """No rows -> empty string (callers decide whether to print a sentinel)."""
    assert format_rows([]) == ""
    assert format_rows([], columns=["a", "b"]) == ""


def test_single_row_single_column() -> None:
    """Single row, single column with auto header."""
    out = format_rows([("hello",)])
    lines = out.splitlines()
    # widths = [max("col0", "hello")] = [5] -> header "col0 ", value "hello".
    assert lines[0] == "col0 "
    assert lines[1] == "hello"


def test_multi_row_multi_column_aligned() -> None:
    """Multiple rows, multiple columns — column widths match max cell width."""
    out = format_rows(
        [
            ("a", "longer"),
            ("bb", "x"),
        ],
        columns=["c1", "c2"],
    )
    lines = out.splitlines()
    # c1 width = max("c1", "a", "bb") = 2; c2 width = max("c2", "longer", "x") = 6.
    # Header: "c1" + " " + "c2" + 4 trailing spaces -> 10 chars.
    assert lines[0] == "c1 c2    "
    # Row 1: "a " + "longer" -> "a  longer" (col1 right-padded to width 2).
    assert lines[1] == "a  longer"
    # Row 2: "bb " + "x" + 4 spaces -> "bb x     " (col2 right-padded to width 6).
    assert lines[2] == "bb x     "


def test_long_value_expands_column() -> None:
    """Long values expand their column width (no truncation in v0.1)."""
    out = format_rows(
        [("short",), ("a-much-longer-value",)],
        columns=["x"],
    )
    lines = out.splitlines()
    # col width = max("x", "short", "a-much-longer-value") = 21.
    assert lines[0] == "x                  "
    assert lines[1] == "short              "
    assert lines[2] == "a-much-longer-value"


def test_header_custom_or_auto() -> None:
    """Header is custom when columns=[...] supplied; auto-named when None."""
    custom = format_rows([(1, 2)], columns=["alpha", "beta"])
    auto = format_rows([(1, 2)])
    # "alpha"/"col0" both 5; "beta"/"col1" both 4 -> numeric cells (1) drive
    # col widths to 5 and 4 respectively, so padding falls on the data row.
    assert custom.splitlines()[0] == "alpha beta"
    assert auto.splitlines()[0] == "col0 col1"


def test_numeric_and_string_cells_render_correctly() -> None:
    """Numeric and string cells both stringify via str()."""
    out = format_rows([(1, "x"), (2, "yy")], columns=["n", "s"])
    lines = out.splitlines()
    # n width = max("n", "1", "2") = 1; s width = max("s", "x", "yy") = 2.
    assert lines[0] == "n s "
    assert lines[1] == "1 x "
    assert lines[2] == "2 yy"