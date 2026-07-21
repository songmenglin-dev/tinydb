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
    ├── Select(columns, from_, where=..., order_by=..., limit=...,
    │         offset=..., group_by=..., aggregates=...)
    ├── Update(table, set_clauses, where=...)
    └── Delete(table, where=...)

    TableRef
    ├── Table(name, alias=None)            # bare table or ``t alias``
    └── Join(left, right, kind, on_expr, using=(), nullable_right=...)

    JoinKind = INNER | LEFT

    Expr
    ├── Literal(value)
    ├── ColumnRef(name, table=None)
    ├── BinaryOp(op, left, right)
    ├── UnaryOp(op, operand)
    └── (Star — sentinel for SELECT *)

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

from tinydb.types.system import Column, TypeTag


# --- marker base classes ------------------------------------------------


class Statement:
    """Marker — every top-level statement inherits from this class."""


class Expr:
    """Marker — every expression node inherits from this class."""


class TableRef:
    """Marker — every table-reference node inherits from this class."""


class JoinKind:
    """JOIN kind discriminator (REQ-JOIN-1, REQ-JOIN-2).

    Plain strings ("INNER" / "LEFT") keep the type closed and trivially
    comparable without an extra ``Enum`` import.  Stored on
    :class:`Join` directly.
    """

    INNER = "INNER"
    LEFT = "LEFT"


# --- table-reference nodes (v0.2 JOIN) ---------------------------------


@dataclass(frozen=True, slots=True)
class Table(TableRef):
    """A bare table reference — ``FROM table_name`` or ``FROM t alias``.

    ``alias`` is ``None`` when the SQL didn't supply one.  When set,
    every column reference in the query must use the alias (REQ-JOIN-4).
    """

    name: str
    alias: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Join(TableRef):
    """A binary JOIN expression — ``left [INNER|LEFT] JOIN right ON ...``.

    ``using`` is the original USING column list (preserved so the planner
    can deduplicate projection columns per REQ-JOIN-8); the planner also
    synthesises the equivalent :attr:`on_expr` from USING when not given
    explicitly.  ``nullable_right`` mirrors the SQL semantics: ``True``
    for LEFT JOIN so the executor pads unmatched right rows with NULL.
    """

    left: "TableRef"
    right: "TableRef"
    kind: str  # JoinKind.INNER | JoinKind.LEFT
    on_expr: Optional["Expr"]  # None when USING-only
    using: Tuple[str, ...] = ()
    nullable_right: bool = False


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
class CreateIndex(Statement):
    """``CREATE [UNIQUE] INDEX <name> ON <table> (<col>)``."""

    name: str
    table: str
    columns: Tuple[str, ...]
    unique: bool = False


@dataclass(frozen=True, slots=True)
class Insert(Statement):
    """``INSERT INTO table [(cols)] VALUES (...)``."""

    table: str
    columns: Optional[Tuple[str, ...]]  # None means "all columns"
    values: Tuple[Tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class Select(Statement):
    """``SELECT ... FROM table_ref [WHERE ...] [ORDER BY ...] [LIMIT ...]``.

    v0.2: ``from_`` carries a :class:`TableRef` (Table or Join).  The
    legacy ``table`` property returns the bare name when ``from_`` is a
    plain :class:`Table` so v0.1 callers and tests continue to work.
    """

    columns: Tuple["Expr", ...]  # ColumnRef / Aggregate / Star / Literal
    from_: "TableRef"
    where: Optional["Expr"] = None
    order_by: Tuple[OrderBy, ...] = ()
    limit: Optional[int] = None
    offset: Optional[int] = None
    group_by: Tuple[str, ...] = ()
    aggregates: Tuple[Aggregate, ...] = ()

    @property
    def table(self) -> str:
        """Legacy accessor: bare table name for single-table SELECTs.

        Raises ``AttributeError`` for JOIN queries — callers handling
        JOIN must walk :attr:`from_` directly.  Kept as a property (not
        a stored field) so the dataclass stays frozen and v0.1 callers
        that read ``stmt.table`` continue to work unchanged.
        """
        if isinstance(self.from_, Table):
            return self.from_.name
        raise AttributeError(
            f"Select.table is undefined for {type(self.from_).__name__} "
            f"FROM clause; use Select.from_ instead"
        )


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


@dataclass(frozen=True, slots=True)
class TypedLiteral(Expr):
    """A type-prefixed literal — ``DATE '2026-07-09'``, ``DECIMAL '0.10'``.

    Covers REQ-TYP-9..14.  ``tag`` is the declared target TypeTag (so
    the executor can validate the column type); ``value`` is the parsed
    Python native (``datetime.date`` / ``datetime.time`` /
    ``datetime.datetime`` / ``decimal.Decimal`` / ``bytes`` / ``(dict |
    list | scalar)``).
    """

    tag: TypeTag
    value: Any


__all__ = [
    "Aggregate",
    "Assignment",
    "BinaryOp",
    "ColumnRef",
    "CreateIndex",
    "CreateTable",
    "Delete",
    "DropTable",
    "Expr",
    "GroupBy",
    "Insert",
    "Join",
    "JoinKind",
    "Limit",
    "Literal",
    "OrderBy",
    "Select",
    "Star",
    "Statement",
    "Table",
    "TableRef",
    "TypedLiteral",
    "UnaryOp",
    "Update",
]
