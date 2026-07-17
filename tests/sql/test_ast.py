"""Smoke tests for the AST node dataclasses.

T-3.2 RED phase.  Verifies that each AST node can be constructed and
that frozen semantics prevent mutation.  Behavioural coverage of the
parser against these nodes lives in tests for T-3.3 / T-3.4.
"""

from __future__ import annotations

import dataclasses

import pytest

from tinydb.sql.ast import (
    Aggregate,
    Assignment,
    BinaryOp,
    ColumnRef,
    CreateTable,
    Delete,
    DropTable,
    GroupBy,
    Insert,
    Limit,
    Literal,
    OrderBy,
    Select,
    Star,
    Statement,
    Table,
    UnaryOp,
    Update,
)
from tinydb.types.system import Column, TypeTag


# --- marker base class --------------------------------------------------


def test_all_statements_subclass_statement():
    """Every top-level statement inherits from Statement for dispatch."""
    stmt_classes = [CreateTable, DropTable, Insert, Select, Update, Delete]
    for cls in stmt_classes:
        assert issubclass(cls, Statement), f"{cls.__name__} should subclass Statement"


# --- statement nodes ----------------------------------------------------


def test_create_table_construction():
    cols = (Column(name="id", tag=TypeTag.Int), Column(name="name", tag=TypeTag.Text))
    ct = CreateTable(name="users", columns=cols)
    assert ct.name == "users"
    assert ct.columns == cols
    assert len(ct.columns) == 2


def test_create_table_is_frozen():
    ct = CreateTable(name="users", columns=(Column(name="id", tag=TypeTag.Int),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        ct.name = "other"  # type: ignore[misc]


def test_drop_table_default_and_if_exists():
    a = DropTable(name="users")
    assert a.if_exists is False
    b = DropTable(name="users", if_exists=True)
    assert b.if_exists is True


def test_insert_with_columns_and_values():
    ins = Insert(
        table="users",
        columns=("id", "name"),
        values=((1, "a"), (2, "b")),
    )
    assert ins.table == "users"
    assert ins.columns == ("id", "name")
    assert ins.values == ((1, "a"), (2, "b"))
    # None columns = INSERT INTO t VALUES (...) means "all columns".
    full = Insert(table="t", columns=None, values=((1,),))
    assert full.columns is None


def test_select_full_clauses():
    sel = Select(
        columns=(ColumnRef(name="id"), ColumnRef(name="name")),
        from_=Table(name="users"),
        where=BinaryOp(op=">=", left=ColumnRef(name="age"), right=Literal(value=18)),
        order_by=(OrderBy(column="name", descending=False),),
        limit=10,
        offset=20,
        group_by=("dept",),
        aggregates=(Aggregate(func="COUNT", column="*"),),
    )
    assert sel.table == "users"
    assert len(sel.columns) == 2
    assert sel.where.op == ">="
    assert sel.limit == 10
    assert sel.offset == 20
    assert sel.group_by == ("dept",)
    assert sel.aggregates[0].func == "COUNT"


def test_select_default_optional_clauses():
    """Bare SELECT * FROM t has no where/order/limit/offset/group/aggregates."""
    sel = Select(columns=(Star(),), from_=Table(name="t"))
    assert sel.where is None
    assert sel.order_by == ()
    assert sel.limit is None
    assert sel.offset is None
    assert sel.group_by == ()
    assert sel.aggregates == ()


def test_update_set_and_where():
    upd = Update(
        table="users",
        set_clauses=(Assignment(column="name", value=Literal(value="b")),),
        where=BinaryOp(op="=", left=ColumnRef(name="id"), right=Literal(value=1)),
    )
    assert upd.table == "users"
    assert upd.set_clauses[0].column == "name"
    assert upd.where.op == "="


def test_delete_with_where():
    de = Delete(
        table="users",
        where=BinaryOp(op="=", left=ColumnRef(name="id"), right=Literal(value=1)),
    )
    assert de.table == "users"
    assert de.where.op == "="


# --- expression nodes ---------------------------------------------------


def test_literal_holds_python_value():
    assert Literal(value=42).value == 42
    assert Literal(value="alice").value == "alice"
    assert Literal(value=None).value is None


def test_column_ref_with_optional_table_qualifier():
    a = ColumnRef(name="id")
    b = ColumnRef(name="id", table="users")
    assert a.table is None
    assert b.table == "users"


def test_binary_op_equality_by_value():
    a = BinaryOp(op="=", left=ColumnRef(name="x"), right=Literal(value=1))
    b = BinaryOp(op="=", left=ColumnRef(name="x"), right=Literal(value=1))
    assert a == b
    assert hash(a) == hash(b)


def test_unary_op_for_is_null_pattern():
    is_null = UnaryOp(
        op="IS NULL",
        operand=ColumnRef(name="x"),
    )
    assert is_null.op == "IS NULL"
    assert is_null.operand.name == "x"


# --- ORDER BY / LIMIT / GROUP BY ---------------------------------------


def test_order_by_default_direction_is_ascending():
    ob = OrderBy(column="id")
    assert ob.descending is False


def test_order_by_descending():
    assert OrderBy(column="created", descending=True).descending is True


def test_limit_standalone_and_with_offset():
    assert Limit(limit=10).offset == 0
    assert Limit(limit=10, offset=20).offset == 20


def test_group_by_is_tuple_of_columns():
    gb = GroupBy(columns=("dept", "team"))
    assert gb.columns == ("dept", "team")


# --- aggregates --------------------------------------------------------


def test_aggregate_count_star():
    a = Aggregate(func="COUNT", column="*")
    assert a.func == "COUNT"
    assert a.column == "*"


def test_aggregate_sum_on_column():
    a = Aggregate(func="SUM", column="amount")
    assert a.func == "SUM"
    assert a.column == "amount"


# --- Star sentinel ------------------------------------------------------


def test_star_is_a_distinct_node():
    """Star is the marker for SELECT * — not a ColumnRef."""
    s = Star()
    assert not isinstance(s, ColumnRef)
    assert isinstance(s, Star)
