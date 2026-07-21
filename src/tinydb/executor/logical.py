"""Logical plan tree — JOIN-aware AST → logical-plan translation.

Split out of :mod:`tinydb.executor.planner` in T-11.1 so the JOIN-aware
rewrites live alongside the JoinNode dataclasses without bloating the
physical planner.  The logical layer is responsible for:

* Resolving aliases into a ``{alias: table_name}`` map (REQ-JOIN-4)
* Rewriting ``USING(col1, col2)`` into an equivalent ``AND`` chain so
  downstream consumers don't need to special-case USING (REQ-JOIN-3)
* Detecting ambiguous unqualified column references (REQ-JOIN-8)
* Emitting a :class:`JoinNode` for any SELECT whose ``from_`` is a
  :class:`Join` (REQ-JOIN-2)

The physical planner (:mod:`tinydb.executor.physical`) later picks the
operator — NLJ vs INLJ — based on index availability (REQ-JOIN-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

from tinydb.errors import TinydbError
from tinydb.sql.ast import (
    BinaryOp,
    ColumnRef,
    Expr,
    Join,
    JoinKind,
    Select,
    Table,
    TableRef,
)

if TYPE_CHECKING:
    from tinydb.storage.catalog import Catalog


class AmbiguousColumnError(TinydbError):
    """A bare column name appeared in more than one JOINed table (REQ-JOIN-8)."""


class UnknownAliasError(TinydbError):
    """A column reference used an alias that was never declared."""

    def __init__(self, alias: str) -> None:
        super().__init__(f"unknown table alias {alias!r}")
        self.alias = alias


class BareColumnNotAliasedError(TinydbError):
    """A bare ``table.col`` was used but the table is aliased (REQ-JOIN-4)."""

    def __init__(self, table: str) -> None:
        super().__init__(
            f"table {table!r} is aliased; use the alias, not the original name"
        )
        self.table = table


# --- LogicalPlan node ---------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class LogicalPlan:
    """Marker — concrete logical-plan nodes are subclasses below.

    Kept as a value-typed node tree so the physical planner can dispatch
    on type (mirroring the existing physical Plan hierarchy in
    :mod:`tinydb.executor.ops`).
    """

    op: str = "LogicalPlan"


@dataclass(frozen=True, slots=True, kw_only=True)
class TableRef_(LogicalPlan):
    """A single-table leaf reference — alias and column list captured here.

    The physical planner wraps this in a SeqScan / IndexScan later;
    keeping the alias on the logical node lets downstream stages
    resolve ``t.col`` without re-reading the catalog.
    """

    table: str
    alias: Optional[str] = None
    op: str = "TableRef"


@dataclass(frozen=True, slots=True, kw_only=True)
class JoinNode(LogicalPlan):
    """Binary join node — replaces the AST :class:`Join` in the logical tree.

    ``on_expr`` is the rewritten equality predicate (USING has been
    converted into ``AND``-chained ``=``); ``using_cols`` is preserved
    so the executor can dedupe projection columns (REQ-JOIN-8).
    """

    left: "LogicalPlan"
    right: "LogicalPlan"
    kind: str  # JoinKind.INNER | JoinKind.LEFT
    on_expr: Optional[Expr]
    using_cols: Sequence[str] = ()
    nullable_right: bool = False
    op: str = "JoinNode"


# --- alias resolution ---------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class AliasMap:
    """Resolved alias → (canonical_table_name, columns).

    Built once per SELECT by :func:`build_alias_map` and shared with
    downstream validation / projection steps.
    """

    aliases: dict  # alias_or_table -> (canonical_name, [col_names])

    def has(self, name: str) -> bool:
        return name in self.aliases

    def canonical(self, name: str) -> str:
        return self.aliases[name][0]


def build_alias_map(from_ref: TableRef) -> AliasMap:
    """Walk ``from_ref`` and collect every alias / table name → table info.

    Used by :func:`validate_columns` and :func:`rewrite_using` to look
    up canonical table names and column lists without re-walking the
    tree per query.
    """
    out: dict = {}

    def _visit(node: TableRef, owner_alias: Optional[str] = None) -> None:
        if isinstance(node, Table):
            # The user may have written ``FROM t alias`` (alias set) or
            # ``FROM t`` (alias=None — original name is the lookup key).
            if node.alias is not None:
                out[node.alias] = (node.name, None)
            else:
                out[node.name] = (node.name, None)
            return
        if isinstance(node, Join):
            _visit(node.left)
            _visit(node.right)

    _visit(from_ref)
    return AliasMap(aliases=out)


# --- USING → ON rewrite -------------------------------------------------


def rewrite_using(j: Join) -> Join:
    """Convert ``USING (col1, col2)`` into an equivalent ``AND`` chain.

    The planner stores the original USING columns on the JoinNode so
    the projection step can dedupe; here we only synthesise the
    on_expr so downstream stages never need a USING special-case.

    For each USING column ``c`` shared by both sides, we generate
    ``left_alias.c = right_alias.c``.  When neither side has an
    alias, the bare column name ``c`` is used on both sides (which
    is well-defined once the alias map is consulted by eval_expr).
    """
    if not j.using:
        return j
    left_alias = _alias_for(j.left)
    right_alias = _alias_for(j.right)
    terms: list = []
    for col in j.using:
        l_name = f"{left_alias}.{col}" if left_alias else col
        r_name = f"{right_alias}.{col}" if right_alias else col
        left_ref = _make_colref(l_name)
        right_ref = _make_colref(r_name)
        terms.append(BinaryOp("=", left=left_ref, right=right_ref))
    on_expr: Expr = terms[0]
    for term in terms[1:]:
        on_expr = BinaryOp("AND", left=on_expr, right=term)
    # Return a new Join with the synthesised on_expr; keep using_cols
    # so the planner / executor can still dedupe projection.
    return Join(
        left=j.left,
        right=j.right,
        kind=j.kind,
        on_expr=on_expr,
        using=j.using,
        nullable_right=j.nullable_right,
    )


def _alias_for(node: TableRef) -> Optional[str]:
    """Return the alias-or-bare-name for a TableRef leaf."""
    if isinstance(node, Table):
        return node.alias or node.name
    if isinstance(node, Join):
        return None  # shouldn't happen — using happens at leaves only
    return None


def _make_colref(qualified: str) -> ColumnRef:
    """``a.b`` → ColumnRef(name='b', table='a'); ``b`` → ColumnRef(name='b')."""
    if "." in qualified:
        a, b = qualified.split(".", 1)
        return ColumnRef(name=b, table=a)
    return ColumnRef(name=qualified)


# --- column validation --------------------------------------------------


def validate_columns(
    expr: Expr,
    alias_map: AliasMap,
    from_ref: TableRef,
    column_owner: Optional[dict] = None,
) -> None:
    """Walk ``expr``; raise :class:`AmbiguousColumnError` / bare-name errors.

    * REQ-JOIN-4: if a table is aliased, ``table.col`` (bare table name)
      is rejected in favour of the alias.
    * REQ-JOIN-8: bare column names that exist in multiple joined tables
      raise :class:`AmbiguousColumnError`.

    ``column_owner`` (optional) is a ``{col_name: set(canonical_table_names)}``
    map built from the live catalog.  When supplied, only columns that
    actually exist in more than one table are flagged as ambiguous.
    Without it, the validator conservatively flags every bare column
    reference in a JOIN context as ambiguous (preserves v0.1 callers
    that pass only AST inputs).
    """
    # Tables that have an alias declared — any reference to them via
    # their canonical (bare) name is rejected.
    aliased_tables: set = set()
    _collect_aliased_canonicals(from_ref, aliased_tables)

    # Build {col_name: [table_names]} for ambiguous-column detection.
    # When a catalog-driven ``column_owner`` is supplied, use it; the
    # legacy AST-only path falls back to a conservative approximation
    # (every table could carry any column).
    catalog_aware = column_owner is not None
    if not catalog_aware:
        tables_with_col: dict = {}
        _collect_columns(from_ref, alias_map, tables_with_col)
        column_owner = tables_with_col

    _walk_expr(
        expr, alias_map, aliased_tables, column_owner, catalog_aware,
    )


def _collect_aliased_canonicals(
    node: TableRef,
    out: set,
) -> None:
    """Populate ``out`` with canonical table names that have an alias."""
    if isinstance(node, Table):
        if node.alias is not None:
            out.add(node.name)
        return
    if isinstance(node, Join):
        _collect_aliased_canonicals(node.left, out)
        _collect_aliased_canonicals(node.right, out)


def _collect_columns(
    node: TableRef,
    alias_map: AliasMap,
    out: dict,
) -> None:
    """Populate ``out[col_name] -> set(canonical_table_names)``."""
    if isinstance(node, Table):
        key = node.alias if node.alias is not None else node.name
        canonical = alias_map.canonical(key)
        # Column lists aren't carried in the AST — for ambiguity check
        # we approximate by treating each table as potentially having
        # any column.  Catalog-driven column resolution happens in the
        # physical planner where we have the TableMeta.
        out.setdefault(canonical, set()).add(canonical)
        return
    if isinstance(node, Join):
        _collect_columns(node.left, alias_map, out)
        _collect_columns(node.right, alias_map, out)


def _walk_expr(
    expr: Expr,
    alias_map: AliasMap,
    aliased_tables: set,
    column_owner: dict,
    catalog_aware: bool = False,
) -> None:
    """Resolve each ``ColumnRef`` against ``column_owner``.

    ``catalog_aware`` is True iff ``column_owner`` was built from the
    live catalog (``{col_name: set(canonical_tables)}``); when False
    the legacy AST-only shape (``{canonical_table: {canonical_table}}``)
    is assumed.
    """
    if isinstance(expr, ColumnRef):
        if expr.table is not None:
            # Accept either the alias OR the canonical (bare) name.
            if expr.table not in alias_map.aliases:
                # Maybe the user wrote the canonical name when the table
                # has an alias — fall through to that check below.
                # Otherwise it's truly unknown.
                if expr.table in column_owner or (
                    catalog_aware and expr.table in _column_owner_tables(column_owner)
                ):
                    # Canonical name used; treat as bare-table reference.
                    if expr.table in aliased_tables:
                        raise BareColumnNotAliasedError(expr.table)
                    return
                raise UnknownAliasError(expr.table)
            # Resolved canonical; check alias hygiene.
            canon = alias_map.canonical(expr.table)
            if canon in aliased_tables and expr.table == canon:
                raise BareColumnNotAliasedError(canon)
            return
        # Bare column — check ambiguous across joined tables.
        if catalog_aware:
            owners = column_owner.get(expr.name, set())
            if len(owners) > 1:
                raise AmbiguousColumnError(
                    f"column {expr.name!r} is ambiguous across JOINed tables; "
                    f"qualify with table alias"
                )
        else:
            # Legacy conservative path: any bare reference in a JOIN
            # context is flagged.  ``column_owner`` here maps
            # ``table -> {table}``; treat its key set as "owners".
            owners = set(column_owner.keys())
            if len(owners) > 1:
                raise AmbiguousColumnError(
                    f"column {expr.name!r} is ambiguous across JOINed tables; "
                    f"qualify with table alias"
                )
        return
    if isinstance(expr, BinaryOp):
        _walk_expr(
            expr.left, alias_map, aliased_tables, column_owner,
            catalog_aware,
        )
        _walk_expr(
            expr.right, alias_map, aliased_tables, column_owner,
            catalog_aware,
        )
    # Literal / TypedLiteral / Star / Aggregate / UnaryOp — no validation.


def _column_owner_tables(column_owner: dict) -> set:
    """Flatten the catalog-driven ``column_owner`` to a set of tables.

    Used when the qualified ref points at the canonical (bare) name
    and we need to know if it's a known table.
    """
    out: set = set()
    for owners in column_owner.values():
        if isinstance(owners, set):
            out.update(owners)
    return out


def _tables_in_from(tables_with_col: dict) -> set:
    """Flatten the {table: {set}} map to a single canonical set of tables."""
    out: set = set()
    for canonical_name in tables_with_col:
        out.add(canonical_name)
    return out


def _is_join_context(tables_with_col: dict) -> bool:
    return len(tables_with_col) > 1


# --- Logical-plan emission ----------------------------------------------


def emit_logical(
    stmt: Select, catalog: Optional["Catalog"] = None,
) -> LogicalPlan:
    """Translate a parsed :class:`Select` into a :class:`LogicalPlan` tree.

    For single-table SELECTs the result is a :class:`TableRef_` (the
    physical planner wraps it in a SeqScan/IndexScan).  For JOINs the
    result is a :class:`JoinNode`; USING clauses are rewritten into
    AND-chained equality predicates (REQ-JOIN-3) and the original
    USING column list is preserved so projection can dedupe
    (REQ-JOIN-8).

    Alias resolution and bare-table detection happen via
    :func:`validate_columns` so any column reference in WHERE / ON /
    the SELECT list is checked once at plan-build time (REQ-JOIN-8).

    ``catalog`` (optional) is the live :class:`Catalog`; when supplied,
    the SELECT-list / WHERE validator uses real column → table
    membership to flag ambiguity only when a bare column genuinely
    exists in more than one table.  Without a catalog, the validator
    falls back to the conservative AST-only behaviour (any bare
    reference in a JOIN context raises) so legacy callers — tests
    that build an AST without a backing DB — still work.
    """
    alias_map = build_alias_map(stmt.from_)
    is_join = not isinstance(stmt.from_, Table)
    # Catalog-driven column-owner map for accurate ambiguity checks.
    column_owner: dict = {}
    if catalog is not None:
        column_owner = _build_catalog_owner(stmt.from_, alias_map, catalog)
    # Validate WHERE / ON columns so ambiguous / unknown aliases
    # raise before any plan node is built.
    if stmt.where is not None:
        validate_columns(
            stmt.where, alias_map, stmt.from_, column_owner=column_owner,
        )
    # T-12.5: SELECT-list bare references that exist in more than one
    # joined table must raise AmbiguousColumnError; this is the
    # user-facing REQ-JOIN-8 hook.
    if is_join:
        for item in stmt.columns:
            if isinstance(item, ColumnRef):
                validate_columns(
                    item, alias_map, stmt.from_, column_owner=column_owner,
                )
    # Note: ORDER BY / GROUP BY bare refs are still validated in the
    # physical planner when the catalog is available.
    return _emit_from(stmt.from_, alias_map)


def _build_catalog_owner(
    from_ref: TableRef,
    alias_map: AliasMap,
    catalog: "Catalog",
) -> dict:
    """Build ``{col_name: set(canonical_tables)}`` from the live catalog.

    Walks the FROM tree, looks up each table's column list, and
    accumulates the inverse index.  The resulting map lets
    :func:`_walk_expr` distinguish bare columns that genuinely live
    in multiple joined tables from bare columns that exist on only
    one side (which are unambiguous even in a JOIN context).
    """
    out: dict = {}

    def _visit(node: TableRef) -> None:
        if isinstance(node, Table):
            key = node.alias if node.alias is not None else node.name
            canonical = alias_map.canonical(key)
            try:
                meta = catalog.get_table(canonical)
            except Exception:
                # Unknown table — skip; downstream code will raise a
                # more specific error (UnknownTableError).
                return
            for col in meta.columns:
                out.setdefault(col.name, set()).add(canonical)
            return
        if isinstance(node, Join):
            _visit(node.left)
            _visit(node.right)

    _visit(from_ref)
    return out


def _emit_from(node: TableRef, alias_map: AliasMap) -> LogicalPlan:
    if isinstance(node, Table):
        return TableRef_(table=node.name, alias=node.alias)
    if isinstance(node, Join):
        # Rewrite USING → AND before emitting the JoinNode.
        rewritten = rewrite_using(node)
        left = _emit_from(rewritten.left, alias_map)
        right = _emit_from(rewritten.right, alias_map)
        return JoinNode(
            left=left,
            right=right,
            kind=rewritten.kind,
            on_expr=rewritten.on_expr,
            using_cols=tuple(rewritten.using),
            nullable_right=rewritten.nullable_right,
        )
    raise TypeError(f"unsupported TableRef node: {type(node).__name__}")


__all__ = [
    "AliasMap",
    "AmbiguousColumnError",
    "BareColumnNotAliasedError",
    "JoinNode",
    "LogicalPlan",
    "TableRef_",
    "UnknownAliasError",
    "build_alias_map",
    "emit_logical",
    "rewrite_using",
    "validate_columns",
]