"""Result formatter — MySQL CLI style ASCII table + line mode.

REQ-CLI-12 / 13 / 14 / 15 / 16.  Stdlib only: no tabulate / rich.

Alignment rules (REQ-CLI-14):

* INT / FLOAT / DECIMAL / BOOL     -> right-aligned
* TEXT / JSON / DATE / TIME / DT   -> left-aligned
* BLOB bytes                      -> ``0x`` + lowercase hex
* ``None``                        -> literal ``NULL``

Width measurement: ``len(s.encode('utf-8'))`` gives a byte count so
non-ASCII characters do not blow the layout; the resulting columns are
crude but stable, matching the v0.2 design note that wide chars can be
worked around with ``.mode line``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


_RIGHT_TYPES: frozenset = frozenset({
    "INT", "INTEGER", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "NUMERIC", "BOOL", "BOOLEAN",
})
_BLOB_TYPES: frozenset = frozenset({"BLOB", "BYTEA"})
_NULL_LITERAL: str = "NULL"


@dataclass(frozen=True)
class ColumnMeta:
    """Column metadata shared between the planner and the renderer."""

    name: str
    type_name: str = "TEXT"


def _display_cell(value: object, type_name: str) -> str:
    """Render a single cell into the string shown inside the table."""
    if value is None:
        return _NULL_LITERAL
    if type_name in _BLOB_TYPES and isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if type_name in _BLOB_TYPES:
        # Some drivers hand us hex already; normalise to ``0x`` prefix.
        s = str(value)
        return s if s.startswith("0x") else "0x" + s
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _display_width(text: str) -> int:
    """Approximate visual width of ``text`` in monospace cells."""
    return len(text.encode("utf-8"))


def _align_for(type_name: str) -> str:
    return "r" if type_name.upper() in _RIGHT_TYPES else "l"


def format_table(
    rows: Sequence[Sequence[object]],
    columns: Sequence[ColumnMeta],
) -> str:
    """Render ``rows`` as a MySQL-style ASCII table.

    Layout::

        +-----+------+-----+
        | id  | name | age |
        +-----+------+-----+
        |   1 | a    |  30 |
        |   2 | bb   |  25 |
        +-----+------+-----+

    Empty rows still emit the header + top/bottom borders so the REPL
    transcript shows a clean ``Empty set (X.XXs)`` immediately after.
    """
    if not columns:
        return ""

    headers = [c.name for c in columns]
    types = [c.type_name for c in columns]
    aligns = [_align_for(t) for t in types]

    # Compute widths from headers and (displayed) cells.
    cells: List[List[str]] = [
        [_display_cell(v, t) for v, t in zip(r, types)]
        for r in rows
    ]
    widths = [len(h.encode("utf-8")) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            if i < len(widths):
                w = _display_width(cell)
                if w > widths[i]:
                    widths[i] = w

    def _border() -> str:
        parts = ["-" * (w + 2) for w in widths]
        return "+" + "+".join(parts) + "+"

    def _row_line(values: Sequence[str]) -> str:
        parts: List[str] = []
        for i, v in enumerate(values):
            pad = widths[i] - _display_width(v)
            if pad < 0:
                pad = 0
            if aligns[i] == "r":
                parts.append(" " * pad + v)
            else:
                parts.append(v + " " * pad)
        return "| " + " | ".join(parts) + " |"

    top = _border()
    header_line = _row_line(headers)
    body_lines = [_row_line(r) for r in cells]
    bottom = _border()

    lines: List[str] = [top, header_line, top]
    lines.extend(body_lines)
    lines.append(bottom)
    return "\n".join(lines)


def format_line_mode(
    rows: Sequence[Sequence[object]],
    columns: Sequence[ColumnMeta],
) -> str:
    """Render ``rows`` as ``column = value`` per line (REQ-CLI-16).

    Each row is separated by a blank line; columns are emitted in the
    order declared.  Values use :func:`_display_cell` so NULL/BLOB look
    the same as in the table format.
    """
    if not columns:
        return ""
    out: List[str] = []
    types = [c.type_name for c in columns]
    for row in rows:
        for col, val in zip(columns, row):
            out.append(f"{col.name} = {_display_cell(val, col.type_name)}")
        out.append("")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def format_timing(n_rows: int, elapsed: float) -> str:
    """Render ``N rows in set (X.XXs)`` / ``Empty set (X.XXs)`` footer."""
    seconds = f"{elapsed:.2f}"
    if n_rows == 0:
        return f"Empty set ({seconds}s)"
    return f"{n_rows} rows in set ({seconds}s)"


def infer_columns_from_rows(
    rows: Sequence[Sequence[object]],
    provided: Optional[Sequence[str]] = None,
) -> List[ColumnMeta]:
    """Best-effort column metadata from observed values.

    Used by meta-commands like ``.tables``/``.schema`` where the caller
    does not have a real ``Column`` available — we still want a sensible
    ``ColumnMeta`` for :func:`format_table`.
    """
    if provided is None:
        width = max((len(r) for r in rows), default=0)
        provided = [f"col{i}" for i in range(width)]
    return [ColumnMeta(name=name, type_name="TEXT") for name in provided]


# --- v0.1 compat: thin shim so argparse_ext keeps compiling -------------
#
# ``tinydb -c '<sql>'`` uses format_rows(); preserve the v0.1 signature
# (rows + columns=optional).  We build a plain ASCII table without type
# alignment so legacy callers get byte-identical output to v0.1.


def _row_widths_legacy(header, rows):
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            cell_len = len(str(cell))
            if i < len(widths):
                if cell_len > widths[i]:
                    widths[i] = cell_len
            else:
                widths.append(cell_len)
    return widths


def format_rows(
    rows,
    columns: Optional[Sequence[str]] = None,
) -> str:
    """Legacy v0.1 helper retained for ``-c`` one-shot SQL mode."""
    if not rows:
        return ""
    row_width = max(len(r) for r in rows)
    if columns is None:
        header: List[str] = [f"col{i}" for i in range(row_width)]
    else:
        header = list(columns)
    while len(header) < row_width:
        header.append(f"col{len(header)}")
    widths = _row_widths_legacy(header, rows)

    def _render(cells):
        parts = []
        for i in range(len(header)):
            text = "" if i >= len(cells) else str(cells[i])
            parts.append(text.ljust(widths[i]))
        return " ".join(parts)

    lines = [_render(header)] + [_render(r) for r in rows]
    return "\n".join(lines)


__all__ = [
    "ColumnMeta",
    "format_table",
    "format_line_mode",
    "format_rows",
    "format_timing",
    "infer_columns_from_rows",
]