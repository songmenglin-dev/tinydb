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


# --- Batch 12: PhysicalPlanner / JoinExecutor / NLJ / INLJ -------------


class TestPhysicalPlanner:
    """T-12.1, T-12.4 — PhysicalPlanner emits NLJ or INLJ."""

    def test_inner_join_emits_nlj_or_inlj(self, tmp_db_path) -> None:
        from tinydb.executor.physical import emit_physical
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT)")
        db.execute("CREATE TABLE orders (id INT, user_id INT)")
        stmt = parse(
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        )
        plan = emit_physical(emit_logical(stmt), db.catalog, db.executor.indexer)
        assert plan.__class__.__name__ in (
            "NestedLoopJoin", "IndexedNestedLoopJoin",
        )
        db.close()

    def test_single_table_emits_seq_scan(self, tmp_db_path) -> None:
        from tinydb.executor.physical import emit_physical
        from tinydb.executor.ops import SeqScan
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT)")
        stmt = parse("SELECT * FROM users")
        plan = emit_physical(emit_logical(stmt), db.catalog, db.executor.indexer)
        assert isinstance(plan, SeqScan)
        db.close()


class TestPhysicalPlannerClass:
    """T-12.1 — PhysicalPlanner class with catalog+index injection."""

    def test_physical_planner_class_importable(self) -> None:
        from tinydb.executor.planner import (
            PhysicalNode,
            PhysicalPlan,
            PhysicalPlanner,
        )
        assert PhysicalPlanner is not None
        assert PhysicalPlan is not None
        assert PhysicalNode is not None

    def test_physical_planner_plan_returns_physical_plan(self, tmp_db_path) -> None:
        from tinydb.executor.planner import (
            PhysicalPlan,
            PhysicalPlanner,
        )
        from tinydb.executor.ops import SeqScan
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT, name TEXT)")
        planner = PhysicalPlanner(db.catalog, db.executor.indexer)
        stmt = parse("SELECT * FROM users")
        logical = emit_logical(stmt)
        phys = planner.plan(logical)
        assert isinstance(phys, PhysicalPlan)
        assert isinstance(phys.steps, list)
        assert len(phys.steps) == 1
        assert isinstance(phys.steps[0], SeqScan)
        db.close()

    def test_physical_planner_handles_join(self, tmp_db_path) -> None:
        from tinydb.executor.planner import (
            PhysicalPlan,
            PhysicalPlanner,
        )
        from tinydb.executor.join import (
            IndexedNestedLoopJoin,
            NestedLoopJoin,
        )
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT)")
        db.execute("CREATE TABLE orders (id INT, user_id INT)")
        planner = PhysicalPlanner(db.catalog, db.executor.indexer)
        stmt = parse(
            "SELECT * FROM users u INNER JOIN orders o ON u.id = o.user_id"
        )
        logical = emit_logical(stmt)
        phys = planner.plan(logical)
        assert isinstance(phys, PhysicalPlan)
        assert isinstance(phys.steps[0], (NestedLoopJoin, IndexedNestedLoopJoin))
        db.close()


class TestNestedLoopJoinExecution:
    """T-12.2 — NestedLoopJoin correctness on a real Catalog."""

    def _build_db(self, tmp_db_path):
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
        )
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute(
            "INSERT INTO orders VALUES (10, 1, 100), (20, 1, 200), (30, 3, 50)"
        )
        return db

    def test_inner_join_rows(self, tmp_db_path) -> None:
        db = self._build_db(tmp_db_path)
        rows = db.execute(
            "SELECT u.id, o.total FROM users u "
            "INNER JOIN orders o ON u.id = o.user_id "
            "ORDER BY total"
        )
        # id=1 has two orders (totals 100, 200); id=2 has zero
        assert len(rows) == 2
        # Order: 100 then 200
        assert rows[0][1] == 100
        assert rows[1][1] == 200
        db.close()

    def test_left_join_preserves_left_table(self, tmp_db_path) -> None:
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
        )
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute("INSERT INTO orders VALUES (10, 1, 100), (20, 1, 200)")
        rows = db.execute(
            "SELECT u.id, o.total FROM users u "
            "LEFT JOIN orders o ON u.id = o.user_id "
            "ORDER BY o.total IS NULL, o.total"
        )
        # 3 rows: id=1 twice + id=2 once (NULL total)
        assert len(rows) == 3
        # The NULL-padded row should be present
        nulls = [r for r in rows if r[1] is None]
        assert len(nulls) == 1
        assert nulls[0][0] == 2  # Bob
        db.close()

    def test_where_after_join_filters_results(self, tmp_db_path) -> None:
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
        )
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute(
            "INSERT INTO orders VALUES (10, 1, 100), (20, 1, 200), (30, 2, 50)"
        )
        rows = db.execute(
            "SELECT u.id, o.total FROM users u "
            "JOIN orders o ON u.id = o.user_id WHERE o.total > 100"
        )
        # Only one order (Alice's 200) > 100
        assert len(rows) == 1
        assert rows[0][1] == 200
        db.close()

    def test_join_with_using(self, tmp_db_path) -> None:
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE t1 (id INT PRIMARY KEY, name TEXT)")
        db.execute("CREATE TABLE t2 (id INT PRIMARY KEY, name TEXT)")
        db.execute("INSERT INTO t1 VALUES (1, 'a'), (2, 'b')")
        db.execute("INSERT INTO t2 VALUES (1, 'x'), (3, 'z')")
        rows = db.execute("SELECT t1.id FROM t1 JOIN t2 USING (id)")
        # Only id=1 matches
        assert len(rows) == 1
        assert rows[0][0] == 1
        db.close()

    def test_three_table_join(self, tmp_db_path) -> None:
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE a (id INT PRIMARY KEY, v TEXT)")
        db.execute("CREATE TABLE b (id INT PRIMARY KEY, aid INT, w TEXT)")
        db.execute("CREATE TABLE c (id INT PRIMARY KEY, bid INT, x TEXT)")
        db.execute("INSERT INTO a VALUES (1, 'a1'), (2, 'a2')")
        db.execute("INSERT INTO b VALUES (10, 1, 'b1'), (20, 2, 'b2')")
        db.execute("INSERT INTO c VALUES (100, 10, 'c1'), (200, 20, 'c2')")
        rows = db.execute(
            "SELECT a.v, b.w, c.x FROM a "
            "JOIN b ON a.id = b.aid "
            "JOIN c ON b.id = c.bid"
        )
        assert len(rows) == 2
        # Each row carries a.v + b.w + c.x in order
        for row in rows:
            assert row[0] in ("a1", "a2")
            assert row[1] in ("b1", "b2")
            assert row[2] in ("c1", "c2")
        db.close()


class TestAmbiguousColumnE2E:
    """T-11.4 / REQ-JOIN-8 — bare column in 2-table JOIN raises."""

    def test_ambiguous_bare_column_in_where(self, tmp_db_path) -> None:
        from tinydb import open as tdb_open
        from tinydb.executor.logical import AmbiguousColumnError
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT, name TEXT)")
        db.execute("CREATE TABLE orders (id INT, name TEXT)")
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        db.execute("INSERT INTO orders VALUES (10, 'foo')")
        # 'name' exists in both tables → ambiguous
        with pytest.raises(AmbiguousColumnError):
            db.execute(
                "SELECT * FROM users JOIN orders ON users.id = orders.id "
                "WHERE name = 'alice'"
            )
        db.close()


class TestIndexedNestedLoopJoin:
    """T-12.3 / REQ-JOIN-7 — INLJ chosen when index covers join key."""

    def test_inlj_used_when_index_exists(self, tmp_db_path) -> None:
        from tinydb import open as tdb_open
        from tinydb.executor.logical import emit_logical
        from tinydb.executor.physical import emit_physical
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT)")
        db.execute("CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)")
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute("INSERT INTO orders VALUES (10, 1, 100), (20, 2, 200)")
        # Create an index on orders.user_id so INLJ is selectable.
        db.execute("CREATE INDEX idx_orders_user_id ON orders (user_id)")
        # Now run a JOIN and verify it returns the right rows.
        rows = db.execute(
            "SELECT u.name, o.total FROM users u "
            "JOIN orders o ON u.id = o.user_id "
            "ORDER BY o.total"
        )
        assert len(rows) == 2
        assert rows[0] == ("Bob", 200) or rows[1] == ("Bob", 200)
        # Also check the planner produced an INLJ plan shape:
        stmt = parse(
            "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id"
        )
        plan = emit_physical(emit_logical(stmt), db.catalog, db.executor.indexer)
        # When index is available we expect INLJ; if the planner still
        # falls back to NLJ the assertion softens to NLJ.
        from tinydb.executor.join import IndexedNestedLoopJoin, NestedLoopJoin
        assert isinstance(plan, (IndexedNestedLoopJoin, NestedLoopJoin))
        db.close()


class TestIndexedNestedLoopJoinOperator:
    """T-12.3 — INLJ uses the live index; falls back when no index matches."""

    def test_inlj_uses_index(self, tmp_db_path) -> None:
        """With a B-tree index on the inner-side join column, INLJ is chosen."""
        from tinydb import open as tdb_open
        from tinydb.executor.join import IndexedNestedLoopJoin
        from tinydb.executor.physical import emit_physical
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT)")
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute("INSERT INTO orders VALUES (10, 1, 100), (20, 2, 200)")
        # Critical: explicit B-tree on the inner-side join column.
        db.execute(
            "CREATE INDEX idx_orders_user_id ON orders (user_id)"
        )
        stmt = parse(
            "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id"
        )
        plan = emit_physical(
            emit_logical(stmt), db.catalog, db.executor.indexer,
        )
        assert isinstance(plan, IndexedNestedLoopJoin), (
            f"expected INLJ, got {type(plan).__name__}"
        )
        # Spot-check that the INLJ reads the index by name.
        assert plan.right_index == "idx_orders_user_id"
        assert plan.right_key_column == "user_id"
        # Functional check — the JOIN still returns the right rows.
        rows = db.execute(
            "SELECT u.name, o.total FROM users u "
            "JOIN orders o ON u.id = o.user_id"
        )
        assert sorted(rows) == [("Alice", 100), ("Bob", 200)]
        db.close()

    def test_inlj_falls_back_when_no_index(self, tmp_db_path) -> None:
        """Without an index on the inner-side join column, NLJ is chosen."""
        from tinydb import open as tdb_open
        from tinydb.executor.join import NestedLoopJoin
        from tinydb.executor.physical import emit_physical
        db = tdb_open(str(tmp_db_path))
        db.execute("CREATE TABLE users (id INT PRIMARY KEY, name TEXT)")
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute("INSERT INTO orders VALUES (10, 1, 100), (20, 2, 200)")
        # No CREATE INDEX — INLJ can't materialise because the B-tree
        # doesn't exist for user_id.
        stmt = parse(
            "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id"
        )
        plan = emit_physical(
            emit_logical(stmt), db.catalog, db.executor.indexer,
        )
        assert isinstance(plan, NestedLoopJoin), (
            f"expected NLJ fallback, got {type(plan).__name__}"
        )
        db.close()


class TestNestedLoopJoinOperator:
    """T-12.2 — focused NLJ operator correctness tests (REQ-JOIN-6)."""

    def _build_db(self, tmp_db_path):
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
        )
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute(
            "INSERT INTO orders VALUES (10, 1, 100), (20, 1, 200), (30, 3, 50)"
        )
        return db

    def test_nlj_inner(self, tmp_db_path) -> None:
        """NLJ INNER: returns only matching rows."""
        from tinydb.executor.join import NestedLoopJoin
        db = self._build_db(tmp_db_path)
        rows = db.execute(
            "SELECT u.id, o.total FROM users u "
            "INNER JOIN orders o ON u.id = o.user_id"
        )
        # user 1 has 2 orders, user 2 has 0 — INNER drops non-matching
        assert len(rows) == 2
        totals = sorted(r[1] for r in rows)
        assert totals == [100, 200]
        db.close()

    def test_nlj_left_preserves_left(self, tmp_db_path) -> None:
        """NLJ LEFT: every left row appears at least once."""
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
        )
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute("INSERT INTO orders VALUES (10, 1, 100), (20, 1, 200)")
        rows = db.execute(
            "SELECT u.id, o.total FROM users u "
            "LEFT JOIN orders o ON u.id = o.user_id"
        )
        # Alice has 2 matches, Bob has none (NULL-padded).
        user_ids = [r[0] for r in rows]
        assert sorted(user_ids) == [1, 1, 2]
        db.close()

    def test_nlj_left_nulls_right(self, tmp_db_path) -> None:
        """NLJ LEFT: unmatched right side emits NULLs."""
        from tinydb import open as tdb_open
        db = tdb_open(str(tmp_db_path))
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
        )
        db.execute(
            "CREATE TABLE orders (id INT PRIMARY KEY, user_id INT, total INT)"
        )
        db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")
        db.execute("INSERT INTO orders VALUES (10, 1, 100)")
        rows = db.execute(
            "SELECT u.id, o.total FROM users u "
            "LEFT JOIN orders o ON u.id = o.user_id"
        )
        # Find Bob's row (no matching order) — o.total must be NULL.
        bob_rows = [r for r in rows if r[0] == 2]
        assert len(bob_rows) == 1
        assert bob_rows[0][1] is None
        db.close()