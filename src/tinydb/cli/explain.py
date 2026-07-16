"""Execution-plan ASCII tree renderer (REQ-CLI-6).

Takes a :class:`tinydb.executor.operators.Plan` (or anything with the
duck-typed ``kind``/``children`` attributes used by the v0.1 operators)
and prints an indented tree:

::

    LogicalPlan
    ├── Filter(id > 18)
    └── SeqScan(users)
    PhysicalPlan
    ├── IndexScan(users.pk_users_id, predicate=id > 18)
    └── ...

Boxes whose ``kind`` is unknown are still walked so plans from the
future join worktree can be rendered.  When ``children`` is missing we
fall back to ``(table,)`` / ``(predicate,)`` introspection for the most
common operator shapes so the tree carries useful info.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def _children_of(node) -> List[object]:
    """Return the child operators of ``node``, or ``[]`` for leaves."""
    children = getattr(node, "children", None)
    if children is not None:
        try:
            return list(children)
        except TypeError:
            pass
    src = getattr(node, "src", None)
    left = getattr(node, "left", None)
    right = getattr(node, "right", None)
    if left is not None or right is not None:
        kids: List[object] = []
        if left is not None:
            kids.append(left)
        if right is not None:
            kids.append(right)
        return kids
    if src is not None:
        return [src]
    return []


def _label(node) -> str:
    """Best-effort human label for ``node``.

    Prefers a ``name`` attribute (some plan types set it explicitly) and
    falls back to the class ``__name__``.  Operator-specific fields
    (``table``, ``predicate``, ``columns``, ``on_expr``) are appended
    in parentheses when present.
    """
    name = getattr(node, "name", None) or type(node).__name__
    table = getattr(node, "table", None)
    predicate = getattr(node, "predicate", None)
    columns = getattr(node, "columns", None)
    on_expr = getattr(node, "on_expr", None)
    items: List[str] = []
    if table is not None:
        items.append(f"table={table}")
    if columns is not None:
        try:
            items.append("cols=[" + ", ".join(str(c) for c in columns) + "]")
        except TypeError:
            items.append(f"cols={columns!r}")
    if predicate is not None:
        items.append(f"pred={predicate!r}")
    if on_expr is not None:
        items.append(f"on={on_expr!r}")
    if not items:
        return name
    return f"{name}(" + ", ".join(items) + ")"


def _render_subtree(node, prefix: str, is_last: bool, out: List[str]) -> None:
    """Recursively render ``node`` into ``out`` using tree glyphs."""
    branch = "└── " if is_last else "├── "
    out.append(prefix + branch + _label(node))
    new_prefix = prefix + ("    " if is_last else "│   ")
    children = _children_of(node)
    for i, child in enumerate(children):
        _render_subtree(child, new_prefix, i == len(children) - 1, out)


def format_plan(root, *, heading: Optional[str] = None) -> str:
    """Render a single plan tree as an ASCII tree.

    Pass ``heading="LogicalPlan"`` / ``heading="PhysicalPlan"`` to label
    the root.  When ``root`` has children we render the root label
    followed by an indented subtree; leaves stand alone.
    """
    lines: List[str] = []
    if heading:
        lines.append(heading)
    if root is None:
        lines.append("└── (empty)")
        return "\n".join(lines)
    children = _children_of(root)
    if not children:
        lines.append("└── " + _label(root))
        return "\n".join(lines)
    lines.append("└── " + _label(root))
    new_prefix = "    "
    for i, child in enumerate(children):
        _render_subtree(child, new_prefix, i == len(children) - 1, lines)
    return "\n".join(lines)


def format_plan_pair(logical, physical) -> str:
    """Render both halves of an EXPLAIN output."""
    parts: List[str] = []
    if logical is not None:
        parts.append(format_plan(logical, heading="LogicalPlan"))
    if physical is not None:
        parts.append(format_plan(physical, heading="PhysicalPlan"))
    return "\n".join(parts)


__all__ = ["format_plan", "format_plan_pair"]