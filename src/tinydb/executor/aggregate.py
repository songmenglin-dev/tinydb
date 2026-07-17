"""Aggregate execution — COUNT / SUM / AVG / MIN / MAX with optional GROUP BY.

NULL semantics (SQLite parity, v0.1):
* ``COUNT(*)`` counts every row; ``COUNT(col)`` skips NULLs.
* ``SUM/AVG/MIN/MAX(col)`` skip NULLs; ``SUM/AVG`` return None over zero
  non-NULL rows, same for ``MIN/MAX``; ``COUNT`` returns 0.
* ``GROUP BY`` skips rows whose key column is NULL.

Output row shape: ``(key_tuple..., agg_value_0, ...)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator, Sequence, Tuple

from tinydb.executor.ops import Plan
from tinydb.executor.planner import UnknownColumnError

if TYPE_CHECKING:
    from tinydb.executor.executor import Executor

Row = tuple


def _new_state() -> dict:
    """Fresh per-aggregate accumulator slots."""
    return {"count": 0, "sum": None, "min": None, "max": None}


def _accumulate(state: dict, func: str, has_value: bool, value: Any) -> None:
    """Fold one row's contribution into ``state`` for ``func``."""
    if func == "COUNT":
        # COUNT(*) bumps unconditionally; COUNT(col) skips NULLs.
        if has_value and value is None:
            return
        state["count"] += 1
        return
    if not has_value or value is None:
        return  # SUM/AVG/MIN/MAX skip NULL.
    if func == "SUM" or func == "AVG":
        state["count"] += 1
        state["sum"] = (state["sum"] or 0) + value
    elif func == "MIN":
        state["min"] = value if state["min"] is None else min(state["min"], value)
    elif func == "MAX":
        state["max"] = value if state["max"] is None else max(state["max"], value)


def _finalize(state: dict, func: str) -> Any:
    """Collapse ``state`` to the final aggregate value."""
    if func == "COUNT":
        return state["count"]
    if func == "MIN" or func == "MAX":
        # MIN/MAX have their own slot; None when no non-NULL values.
        return state[func.lower()]
    if state["count"] == 0:
        return None
    if func == "SUM":
        return state["sum"]
    return state["sum"] / state["count"]  # AVG


def _resolve(row: Row, column: str, n2i: dict) -> Tuple[bool, Any]:
    """``(has_value, value)`` for ``column`` against ``row``.

    ``has_value`` is False for ``*`` (COUNT(*)) — no column read.
    """
    if column == "*":
        return (False, None)
    if column not in n2i:
        raise UnknownColumnError(column)
    return (True, row[n2i[column]])


@dataclass(frozen=True, slots=True, kw_only=True)
class Aggregate(Plan):
    """Apply ``aggregates`` optionally grouped by ``keys``.

    ``aggregates`` is a sequence of ``(func, column)`` pairs (column
    may be ``"*"`` for COUNT).  ``keys`` empty → single aggregate row.
    """

    src: "Plan"
    aggregates: Sequence[tuple]  # [(func, column), ...]
    keys: Sequence[str] = ()
    op_name: str = "Aggregate"

    @property
    def table(self) -> str:  # type: ignore[override]
        return self.src.table

    def open(self, ctx: "Executor") -> Iterator[Row]:  # noqa: F821
        # T-13.1: when the source is a JOIN tree, ``self.table`` is the
        # leftmost leaf and ``name_to_idx_for(self.table)`` only sees
        # that side's columns — so right-side columns (the very thing
        # aggregates like ``SUM(o.total)`` need) would be invisible.
        # Walk the source for a JOIN and use the merged recursive
        # ``row_n2i_for_plan`` map instead.
        from tinydb.executor.join import (
            IndexedNestedLoopJoin,
            NestedLoopJoin,
            row_n2i_for_plan,
        )
        candidate = self.src
        while hasattr(candidate, "src") and not isinstance(
            candidate, (NestedLoopJoin, IndexedNestedLoopJoin)
        ):
            candidate = candidate.src
        if isinstance(candidate, (NestedLoopJoin, IndexedNestedLoopJoin)):
            n2i = row_n2i_for_plan(candidate, ctx)
        else:
            n2i = ctx.name_to_idx_for(self.table)
        # ``groups[key]`` is a tuple of per-aggregate state dicts so
        # each func maintains its own slots without cross-talk.
        groups: dict = {}
        order: list = []
        for row in self.src.open(ctx):
            key = self._extract_key(row, n2i)
            if key is None:
                continue  # GROUP BY: drop rows with NULL key.
            if key not in groups:
                groups[key] = tuple(_new_state() for _ in self.aggregates)
                order.append(key)
            for state, (func, column) in zip(groups[key], self.aggregates):
                has_value, value = _resolve(row, column, n2i)
                _accumulate(state, func, has_value, value)
        return self._emit(groups, order)

    def _extract_key(self, row: Row, n2i: dict) -> Tuple:
        """Group key tuple — ``None`` when any key column is NULL."""
        if not self.keys:
            return ()
        parts: list = []
        for col in self.keys:
            if col not in n2i:
                raise UnknownColumnError(col)
            v = row[n2i[col]]
            if v is None:
                return None
            parts.append(v)
        return tuple(parts)

    def _emit(self, groups: dict, order: list) -> Iterator[Row]:
        # Empty input with no GROUP BY: surface one row of zeros / Nones.
        if not self.keys and not order:
            empty = tuple(_new_state() for _ in self.aggregates)
            yield tuple(
                _finalize(state, func)
                for state, (func, _) in zip(empty, self.aggregates)
            )
            return
        for key in order:
            states = groups[key]
            yield tuple(key) + tuple(
                _finalize(state, func)
                for state, (func, _) in zip(states, self.aggregates)
            )


__all__ = ["Aggregate"]
