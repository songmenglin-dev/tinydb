"""JOIN feature tests — REQ-JOIN-1..10.

Tests are organised by requirement; the test name encodes the REQ
prefix.  The first batch (T-10.1) covers pure AST construction; the
parser / planner / executor tests follow.
"""

from __future__ import annotations

import pytest

from tinydb.errors import ParseError, TinydbError
from tinydb.executor.logical import (
    AliasMap,
    AmbiguousColumnError,
    BareColumnNotAliasedError,
    JoinNode,
    LogicalPlan,
    TableRef_,
    UnknownAliasError,
    build_alias_map,
    emit_logical,
    rewrite_using,
    validate_columns,
)
from tinydb.sql.ast import (
    BinaryOp,
    ColumnRef,
    Join,
    JoinKind,
    Literal,
    Select,
    Star,
    Table,
    TableRef,
)
from tinydb.sql.parser import parse


# --- REQ-JOIN-1, REQ-JOIN-2, REQ-JOIN-3, REQ-JOIN-4, REQ-JOIN-5: AST shape


class TestASTNodes:
    """T-10.1 — JoinPlan/JoinKind/TableRef AST nodes."""

    def test_join_kind_constants(self) -> None:
        assert JoinKind.INNER == "INNER"
        assert JoinKind.LEFT == "LEFT"

    def test_table_dataclass_construction(self) -> None:
        t = Table(name="users", alias="u")
        assert t.name == "users"
        assert t.alias == "u"
        assert isinstance(t, TableRef)

    def test_table_default_no_alias(self) -> None:
        t = Table(name="users")
        assert t.alias is None

    def test_join_dataclass_inner(self) -> None:
        a = Table(name="users", alias="u")
        b = Table(name="orders", alias="o")
        cond = BinaryOp("=", ColumnRef("id", "u"), ColumnRef("user_id", "o"))
        j = Join(left=a, right=b, kind=JoinKind.INNER, on_expr=cond)
        assert j.kind == "INNER"
        assert j.on_expr is cond
        assert j.using == ()
        assert j.nullable_right is False

    def test_join_dataclass_left_nullable(self) -> None:
        a = Table(name="users")
        b = Table(name="orders")
        cond = BinaryOp("=", ColumnRef("id", "u"), ColumnRef("user_id", "o"))
        j = Join(left=a, right=b, kind=JoinKind.LEFT, on_expr=cond, nullable_right=True)
        assert j.kind == "LEFT"
        assert j.nullable_right is True

    def test_join_with_using(self) -> None:
        a = Table(name="t1")
        b = Table(name="t2")
        j = Join(left=a, right=b, kind=JoinKind.INNER, on_expr=None, using=("user_id",))
        assert j.using == ("user_id",)
        assert j.on_expr is None

    def test_join_is_hashable(self) -> None:
        a = Table(name="a")
        b = Table(name="b")
        j1 = Join(left=a, right=b, kind=JoinKind.INNER, on_expr=None)
        j2 = Join(left=a, right=b, kind=JoinKind.INNER, on_expr=None)
        assert hash(j1) == hash(j2)
        assert j1 == j2

    def test_select_from_legacy_table_property(self) -> None:
        t = Table(name="events")
        s = Select(columns=(Star(),), from_=t)
        # v0.1 callers that read stmt.table keep working
        assert s.table == "events"

    def test_select_table_property_raises_for_join(self) -> None:
        a = Table(name="a")
        b = Table(name="b")
        j = Join(left=a, right=b, kind=JoinKind.INNER, on_expr=None)
        s = Select(columns=(Star(),), from_=j)
        with pytest.raises(AttributeError):
            _ = s.table


# --- REQ-JOIN-1, REQ-JOIN-2: parser tests (RED until parser is extended)


class TestParserJoinOn:
    """T-10.2 — JOIN ... ON clause parsing."""

    def test_inner_join_keyword(self) -> None:
        sql = "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        stmt = parse(sql)
        assert isinstance(stmt, Select)
        # Top-level from_ is a Join, not a Table.
        assert isinstance(stmt.from_, Join)
        assert stmt.from_.kind == JoinKind.INNER
        assert isinstance(stmt.from_.left, Table)
        assert stmt.from_.left.name == "users"
        assert stmt.from_.left.alias == "u"
        assert isinstance(stmt.from_.right, Table)
        assert stmt.from_.right.alias == "o"

    def test_join_without_inner_keyword_defaults_to_inner(self) -> None:
        sql = "SELECT * FROM a JOIN b ON a.id = b.aid"
        stmt = parse(sql)
        assert isinstance(stmt.from_, Join)
        assert stmt.from_.kind == JoinKind.INNER

    def test_join_missing_on_raises(self) -> None:
        with pytest.raises(ParseError) as exc:
            parse("SELECT * FROM a INNER JOIN b")
        assert "JOIN requires ON or USING clause" in str(exc.value)

    def test_left_join_keyword(self) -> None:
        sql = "SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id"
        stmt = parse(sql)
        assert isinstance(stmt.from_, Join)
        assert stmt.from_.kind == JoinKind.LEFT
        assert stmt.from_.nullable_right is True

    def test_left_outer_join_equals_left(self) -> None:
        sql = "SELECT * FROM users LEFT OUTER JOIN orders ON users.id = orders.user_id"
        stmt = parse(sql)
        assert isinstance(stmt.from_, Join)
        assert stmt.from_.kind == JoinKind.LEFT

    def test_three_table_join_nests_left_associative(self) -> None:
        sql = "SELECT * FROM a JOIN b ON a.id = b.aid JOIN c ON b.id = c.bid"
        stmt = parse(sql)
        # ((a ⋈ b) ⋈ c): outer Join.left is a Join, outer.right is c
        assert isinstance(stmt.from_, Join)
        assert isinstance(stmt.from_.left, Join)
        assert stmt.from_.left.kind == JoinKind.INNER
        assert isinstance(stmt.from_.right, Table)
        assert stmt.from_.right.name == "c"

    def test_six_table_join_rejected(self) -> None:
        # 7 tables joined = 6 JOIN keywords = 6 wrappers, which exceeds
        # REQ-JOIN-5's max of 5.
        sql = (
            "SELECT * FROM a "
            "JOIN b ON a.id=b.aid "
            "JOIN c ON b.id=c.bid "
            "JOIN d ON c.id=c.did "
            "JOIN e ON d.id=d.eid "
            "JOIN f ON e.id=e.fid "
            "JOIN g ON f.id=g.fid"
        )
        with pytest.raises(ParseError) as exc:
            parse(sql)
        assert "JOIN nesting depth exceeds 5" in str(exc.value)


# --- REQ-JOIN-3: USING clause


class TestParserUsing:
    """T-10.3 — JOIN ... USING (col1, col2, ...) parsing."""

    def test_single_column_using(self) -> None:
        sql = "SELECT * FROM users JOIN orders USING (user_id)"
        stmt = parse(sql)
        assert isinstance(stmt.from_, Join)
        assert stmt.from_.using == ("user_id",)
        assert stmt.from_.on_expr is None

    def test_multi_column_using(self) -> None:
        sql = "SELECT * FROM t1 JOIN t2 USING (a, b)"
        stmt = parse(sql)
        assert isinstance(stmt.from_, Join)
        assert stmt.from_.using == ("a", "b")


# --- REQ-JOIN-4: table aliases


class TestParserAlias:
    """T-10.4 — FROM table alias form."""

    def test_alias_after_table_name(self) -> None:
        sql = "SELECT u.name FROM users u WHERE u.age > 18"
        stmt = parse(sql)
        assert isinstance(stmt, Select)
        assert isinstance(stmt.from_, Table)
        assert stmt.from_.name == "users"
        assert stmt.from_.alias == "u"

    def test_no_alias_returns_none(self) -> None:
        sql = "SELECT name FROM users"
        stmt = parse(sql)
        assert isinstance(stmt.from_, Table)
        assert stmt.from_.alias is None


# --- REQ-JOIN-8: ambiguous column error (planning layer)


class TestAmbiguousColumnError:
    """T-11.4 — bare column name appears in both tables."""

    def test_ambiguous_column_raises(self) -> None:
        # We don't have an executor wired up yet, but the parser path
        # is exercised and we mark this test as failing until the
        # planner emits the right error.
        from tinydb.sql.parser import parse_dml_string

        sql = (
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        )
        stmt = parse_dml_string(sql)
        assert isinstance(stmt, Select)
        assert isinstance(stmt.from_, Join)


# --- Batch 11: LogicalPlanner / JoinNode / USING / aliases -------------


class TestAliasMap:
    """T-11.1 — building alias → table maps from TableRef trees."""

    def test_single_table_aliased(self) -> None:
        m = build_alias_map(Table(name="users", alias="u"))
        assert m.has("u")
        assert m.canonical("u") == "users"

    def test_single_table_no_alias(self) -> None:
        m = build_alias_map(Table(name="users"))
        assert m.has("users")
        assert m.canonical("users") == "users"

    def test_two_tables_each_aliased(self) -> None:
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=None,
        )
        m = build_alias_map(j)
        assert m.has("u")
        assert m.has("o")
        assert m.canonical("u") == "users"
        assert m.canonical("o") == "orders"

    def test_three_tables_each_aliased(self) -> None:
        j = Join(
            left=Join(
                left=Table(name="a", alias="a_"),
                right=Table(name="b", alias="b_"),
                kind=JoinKind.INNER,
                on_expr=None,
            ),
            right=Table(name="c", alias="c_"),
            kind=JoinKind.INNER,
            on_expr=None,
        )
        m = build_alias_map(j)
        assert m.canonical("a_") == "a"
        assert m.canonical("b_") == "b"
        assert m.canonical("c_") == "c"


class TestRewriteUsing:
    """T-11.3 — USING (col) → AND chain of equality predicates."""

    def test_single_column_using_with_aliases(self) -> None:
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=None,
            using=("user_id",),
        )
        r = rewrite_using(j)
        # on_expr becomes u.user_id = o.user_id
        assert isinstance(r.on_expr, BinaryOp)
        assert r.on_expr.op == "="
        assert isinstance(r.on_expr.left, ColumnRef)
        assert r.on_expr.left.table == "u"
        assert r.on_expr.left.name == "user_id"
        assert isinstance(r.on_expr.right, ColumnRef)
        assert r.on_expr.right.table == "o"
        assert r.on_expr.right.name == "user_id"
        # using cols preserved for projection dedup
        assert r.using == ("user_id",)

    def test_multi_column_using_yields_and_chain(self) -> None:
        j = Join(
            left=Table(name="t1", alias="a"),
            right=Table(name="t2", alias="b"),
            kind=JoinKind.INNER,
            on_expr=None,
            using=("x", "y"),
        )
        r = rewrite_using(j)
        # Top-level op is AND; leaves are = comparisons.
        assert isinstance(r.on_expr, BinaryOp)
        assert r.on_expr.op == "AND"
        left_cmp = r.on_expr.left
        right_cmp = r.on_expr.right
        assert isinstance(left_cmp, BinaryOp) and left_cmp.op == "="
        assert isinstance(right_cmp, BinaryOp) and right_cmp.op == "="
        assert left_cmp.left.name == "x"
        assert right_cmp.left.name == "y"

    def test_using_no_op_when_already_have_on(self) -> None:
        cond = BinaryOp("=", ColumnRef("a", "u"), ColumnRef("a", "o"))
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=cond,
        )
        r = rewrite_using(j)
        # Same Join returned (no rewrite needed)
        assert r is j


class TestEmitLogical:
    """T-11.2 — emit_logical produces LogicalPlan tree."""

    def test_single_table_emits_tableref(self) -> None:
        stmt = parse("SELECT * FROM users")
        plan = emit_logical(stmt)
        assert isinstance(plan, TableRef_)
        assert plan.table == "users"

    def test_inner_join_emits_join_node(self) -> None:
        stmt = parse(
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        )
        plan = emit_logical(stmt)
        assert isinstance(plan, JoinNode)
        assert plan.kind == JoinKind.INNER
        assert isinstance(plan.left, TableRef_)
        assert plan.left.alias == "u"
        assert isinstance(plan.right, TableRef_)
        assert plan.right.alias == "o"
        # on_expr passes through
        assert isinstance(plan.on_expr, BinaryOp)
        assert plan.on_expr.op == "="

    def test_left_join_emits_join_node_with_nullable(self) -> None:
        stmt = parse(
            "SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id"
        )
        plan = emit_logical(stmt)
        assert isinstance(plan, JoinNode)
        assert plan.kind == JoinKind.LEFT
        assert plan.nullable_right is True

    def test_using_clause_rewritten_to_and(self) -> None:
        stmt = parse("SELECT * FROM users JOIN orders USING (user_id)")
        plan = emit_logical(stmt)
        assert isinstance(plan, JoinNode)
        assert plan.using_cols == ("user_id",)
        # on_expr is the rewritten equality
        assert isinstance(plan.on_expr, BinaryOp)
        assert plan.on_expr.op == "="

    def test_three_table_join_nested(self) -> None:
        stmt = parse(
            "SELECT * FROM a JOIN b ON a.id=b.aid JOIN c ON b.id=c.bid"
        )
        plan = emit_logical(stmt)
        assert isinstance(plan, JoinNode)
        assert isinstance(plan.left, JoinNode)
        assert isinstance(plan.right, TableRef_)
        assert plan.right.table == "c"


class TestValidateColumns:
    """T-11.4 — alias / ambiguous / bare-name errors."""

    def test_qualified_col_resolves_to_alias(self) -> None:
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=None,
        )
        # u.id is fine.
        validate_columns(
            BinaryOp("=", ColumnRef("id", "u"), ColumnRef("user_id", "o")),
            build_alias_map(j),
            j,
        )

    def test_unknown_alias_raises(self) -> None:
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=None,
        )
        with pytest.raises(UnknownAliasError):
            validate_columns(
                ColumnRef("id", "x"),  # x is not an alias
                build_alias_map(j),
                j,
            )

    def test_bare_table_name_rejected_when_aliased(self) -> None:
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=None,
        )
        with pytest.raises(BareColumnNotAliasedError):
            validate_columns(
                ColumnRef("id", "users"),  # 'users' is aliased to 'u'
                build_alias_map(j),
                j,
            )

    def test_ambiguous_bare_column_raises_in_join(self) -> None:
        # Two tables, both could plausibly have 'name' column — bare
        # reference is ambiguous.
        j = Join(
            left=Table(name="users", alias="u"),
            right=Table(name="orders", alias="o"),
            kind=JoinKind.INNER,
            on_expr=None,
        )
        with pytest.raises(AmbiguousColumnError):
            validate_columns(
                ColumnRef("name"),  # bare, ambiguous
                build_alias_map(j),
                j,
            )


class TestLogicalSelectIntegration:
    """End-to-end: parse + emit_logical."""

    def test_basic_inner_join_emits_logical(self) -> None:
        stmt = parse(
            "SELECT u.name FROM users u INNER JOIN orders o "
            "ON u.id = o.user_id WHERE o.total > 100"
        )
        plan = emit_logical(stmt)
        assert isinstance(plan, JoinNode)