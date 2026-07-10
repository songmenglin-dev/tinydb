"""SQL AST — frozen-dataclass nodes produced by the parser.

The AST is purely value-typed: every node inherits from the empty
:class:`Statement` or :class:`Expr` marker (or :class:`OrderBy` /
:class:`Limit` / :class:`GroupBy` / :class:`Aggregate` /
:class:`Assignment` helpers).  Frozen + slots means each node is
immutable, hashable, and cheap to allocate — the executor will freely
build and discard AST fragments.

Node hierarchy
--------------
::

    Statement
    ├── CreateTable(name, columns)
    ├── DropTable(name, if_exists=False)
    ├── Insert(table, columns, values)
    ├── Select(columns, table, where=..., order_by=..., limit=...,
    │         offset=..., group_by=..., aggregates=...)
    ├── Update(table, set_clauses, where=...)
    └── Delete(table, where=...)

    Expr
    ├── Literal(value)
    ├── ColumnRef(name, table=None)
    ├── BinaryOp(op, left, right)
    ├── UnaryOp(op, operand)
    └── (Star — sentinel for SELECT *)

    Helpers: Assignment, OrderBy, Limit, GroupBy, Aggregate
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from tinydb.types.system import Column


# --- marker base classes ------------------------------------------------


class Statement:
    """Marker — every top-level statement inherits from this class."""


class Expr:
    """Marker — every expression node inherits from this class."""


# --- misc helpers -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Star:
    """Sentinel for ``SELECT *`` (or similar all-columns positions).

    Distinct from :class:`ColumnRef` so the executor can dispatch on
    type without inspecting string values.
    """


@dataclass(frozen=True, slots=True)
class Assignment:
    """``SET column = expr`` inside an :class:`Update` statement."""

    column: str
    value: "Expr"


@dataclass(frozen=True, slots=True)
class OrderBy:
    """One term inside ``ORDER BY <column> [ASC|DESC]``.

    ``descending=False`` means ASC (the SQL default).
    """

    column: str
    descending: bool = False


@dataclass(frozen=True, slots=True)
class Limit:
    """``LIMIT n [OFFSET m]`` clause."""

    limit: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class GroupBy:
    """``GROUP BY col1, col2, ...`` clause."""

    columns: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Aggregate:
    """Aggregate function call (``COUNT(*)``, ``SUM(col)``, ...).

    ``column == "*"`` is the wildcard form of ``COUNT``.
    """

    func: str  # 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX'
    column: str  # column name or '*'


# --- statement nodes ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateTable(Statement):
    """``CREATE TABLE name (col TYPE [constraints], ...)``."""

    name: str
    columns: Tuple[Column, ...]


@dataclass(frozen=True, slots=True)
class DropTable(Statement):
    """``DROP TABLE [IF EXISTS] name``."""

    name: str
    if_exists: bool = False


@dataclass(frozen=True, slots=True)
class Insert(Statement):
    """``INSERT INTO table [(cols)] VALUES (...)``."""

    table: str
    columns: Optional[Tuple[str, ...]]  # None means "all columns"
    values: Tuple[Tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class Select(Statement):
    """``SELECT ... FROM table [WHERE ...] [ORDER BY ...] [LIMIT ...]``."""

    columns: Tuple["Expr", ...]  # ColumnRef / Aggregate / Star / Literal
    table: str
    where: Optional["Expr"] = None
    order_by: Tuple[OrderBy, ...] = ()
    limit: Optional[int] = None
    offset: Optional[int] = None
    group_by: Tuple[str, ...] = ()
    aggregates: Tuple[Aggregate, ...] = ()


@dataclass(frozen=True, slots=True)
class Update(Statement):
    """``UPDATE table SET ... WHERE ...``."""

    table: str
    set_clauses: Tuple[Assignment, ...]
    where: Optional["Expr"] = None


@dataclass(frozen=True, slots=True)
class Delete(Statement):
    """``DELETE FROM table WHERE ...``."""

    table: str
    where: Optional["Expr"] = None


# --- expression nodes --------------------------------------------------


@dataclass(frozen=True, slots=True)
class Literal(Expr):
    """A literal value: ``42``, ``9.99``, ``'hello'``, ``TRUE``, ``NULL``.

    The Python value carries enough type info (``int`` / ``float`` /
    ``str`` / ``bool`` / ``None``) for the executor to match a column's
    declared TypeTag.  See ``tinydb.types.coerce`` for the rules.
    """

    value: Any


@dataclass(frozen=True, slots=True)
class ColumnRef(Expr):
    """A column reference, optionally qualified by table (``t.col``)."""

    name: str
    table: Optional[str] = None


@dataclass(frozen=True, slots=True)
class BinaryOp(Expr):
    """``left op right`` — comparison / arithmetic / logical / IS."""

    op: str  # '=', '!=', '<', '<=', '>', '>=', '+', '-', '*', '/', 'AND', 'OR'
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True, slots=True)
class UnaryOp(Expr):
    """A unary expression — ``NOT x`` / ``x IS NULL`` / ``x IS NOT NULL``."""

    op: str  # 'NOT' | 'IS NULL' | 'IS NOT NULL'
    operand: "Expr"


__all__ = [
    "Aggregate",
    "Assignment",
    "BinaryOp",
    "ColumnRef",
    "CreateTable",
    "Delete",
    "DropTable",
    "Expr",
    "GroupBy",
    "Insert",
    "Limit",
    "Literal",
    "OrderBy",
    "Select",
    "Star",
    "Statement",
    "UnaryOp",
    "Update",
]
