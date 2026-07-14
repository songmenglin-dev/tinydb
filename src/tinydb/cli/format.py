"""Result table formatter (T-8.2).

Renders ``list[tuple]`` rows as an aligned ASCII table for CLI output.

Design notes
------------
- First row is treated as the *header*.  When ``columns`` is ``None``
  the header defaults to ``col0``, ``col1``, ...; when supplied it is
  used verbatim.
- Each cell is padded to its column's max width (``max(header, *col)``).
- v0.1 uses ``len()`` for width measurement — ASCII-only.  Non-ASCII
  cells with multi-byte / wide characters will misalign; documented as
  a known limitation in T-8.2 / T-9.
- Empty input returns ``""`` so the caller can decide whether to print
  a "(0 rows)" sentinel.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence


def _row_widths(header: Sequence[str], rows: Iterable[Sequence[object]]) -> List[int]:
    """Compute per-column widths = max of (header, every cell in column).

    Robust against ragged rows: short rows are treated as empty for the
    missing tail columns, so a 3-column header + 2-column row simply
    uses 0 widths for the missing tail when computing the next pass.
    """
    widths = [len(h) for h in header]
    for row in rows:
        for i, cell in enumerate(row):
            cell_len = len(str(cell))
            if i < len(widths):
                if cell_len > widths[i]:
                    widths[i] = cell_len
            else:
                # Row has more cells than header — extend.
                widths.append(cell_len)
        # Header has more cells than row — leave the trailing widths as-is.
    return widths


def format_rows(
    rows: List[Sequence[object]],
    columns: Optional[Sequence[str]] = None,
) -> str:
    """Render ``rows`` as an aligned ASCII table.

    Parameters
    ----------
    rows:
        Result rows from the executor (each row is a tuple / sequence).
    columns:
        Optional column-name list.  When ``None``, defaults to
        ``col0``, ``col1``, ... matching the row width.

    Returns
    -------
    str
        Multi-line ASCII table (header + one row per input row),
        separated by ``\\n``.  Empty string for empty input.
    """
    if not rows:
        return ""

    row_width = max(len(r) for r in rows)
    if columns is None:
        header: List[str] = [f"col{i}" for i in range(row_width)]
    else:
        header = list(columns)
    # Pad header if shorter than row_width.
    while len(header) < row_width:
        header.append(f"col{len(header)}")

    widths = _row_widths(header, rows)

    def _render(cells: Sequence[object]) -> str:
        parts = []
        for i in range(len(header)):
            text = "" if i >= len(cells) else str(cells[i])
            parts.append(text.ljust(widths[i]))
        # Single space separator between columns (sqlite-style).
        return " ".join(parts)

    lines = [_render(header)] + [_render(r) for r in rows]
    return "\n".join(lines)


__all__ = ["format_rows"]