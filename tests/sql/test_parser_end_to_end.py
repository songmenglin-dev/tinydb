"""End-to-end parser tests using realistic SQL fixtures.

T-3.8 RED phase.  Locks in the top-level ``parse(sql)`` public entry
point with realistic SQL strings spanning DDL + DML + aggregates +
type literals.  These are smoke tests for the whole pipeline
(tokenize → parse → AST) and act as the contract the executor will
later consume.

Each test feeds a real-world-looking SQL statement into
:func:`tinydb.sql.parser.parse` and asserts on the resulting AST
shape.  No new parser code is expected — these tests should pass
once T-3.1..T-3.7 are green.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from tinydb.sql.ast import (
    Aggregate,
    Assignment,
    BinaryOp,
    ColumnRef,
    CreateTable,
    Delete,
    DropTable,
    Insert,
    Literal,
    OrderBy,
    Select,
    Star,
    TypedLiteral,
    Update,
)
from tinydb.sql.parser import parse
from tinydb.types.system import Column, TypeTag


# --- DDL fixtures -------------------------------------------------------


@pytest.mark.unit
def test_e2e_create_users_table_realistic_schema():
    sql = """
    CREATE TABLE users (
        id        INT    PRIMARY KEY,
        email     TEXT   NOT NULL UNIQUE,
        full_name TEXT   NOT NULL,
        age       INT,
        is_active BOOL
    )
    """
    stmt = parse(sql)
    assert isinstance(stmt, CreateTable)
    assert stmt.name == "users"
    cols = {c.name: c for c in stmt.columns}
    assert cols["id"].primary_key is True
    assert cols["email"].not_null is True
    assert cols["email"].unique is True
    assert cols["full_name"].not_null is True
    assert cols["age"].not_null is False


@pytest.mark.unit
def test_e2e_create_orders_table_with_various_types():
    sql = """
    CREATE TABLE orders (
        id          INT       PRIMARY KEY,
        customer_id INT       NOT NULL,
        amount      DECIMAL,
        placed_at   DATETIME,
        shipped_at  DATETIME,
        notes       TEXT
    )
    """
    stmt = parse(sql)
    assert isinstance(stmt, CreateTable)
    by_name = {c.name: c for c in stmt.columns}
    assert by_name["amount"].tag is TypeTag.Decimal
    assert by_name["placed_at"].tag is TypeTag.Datetime


@pytest.mark.unit
def test_e2e_drop_table_with_if_exists():
    stmt = parse("DROP TABLE IF EXISTS legacy_data")
    assert isinstance(stmt, DropTable)
    assert stmt.name == "legacy_data"
    assert stmt.if_exists is True


# --- DML fixtures -------------------------------------------------------


@pytest.mark.unit
def test_e2e_insert_single_row_with_type_literals():
    sql = """
    INSERT INTO events (id, occurred_at, payload)
    VALUES (1, DATETIME '2026-07-09 14:30:00', JSON '{"user": 42}')
    """
    stmt = parse(sql)
    assert isinstance(stmt, Insert)
    assert stmt.table == "events"
    assert stmt.columns == ("id", "occurred_at", "payload")
    row = stmt.values[0]
    assert row[0] == 1
    assert row[1] == TypedLiteral(
        TypeTag.Datetime, datetime.datetime(2026, 7, 9, 14, 30, 0),
    )
    assert row[2] == TypedLiteral(TypeTag.Json, {"user": 42})


@pytest.mark.unit
def test_e2e_insert_multi_row_bulk_load():
    sql = """
    INSERT INTO users (id, email) VALUES
        (1, 'alice@example.com'),
        (2, 'bob@example.com'),
        (3, 'carol@example.com')
    """
    stmt = parse(sql)
    assert len(stmt.values) == 3
    assert stmt.values[0] == (1, "alice@example.com")
    assert stmt.values[2] == (3, "carol@example.com")


@pytest.mark.unit
def test_e2e_select_with_compound_where_and_order_limit():
    sql = """
    SELECT id, email
    FROM users
    WHERE age >= 18 AND is_active = TRUE
    ORDER BY id ASC
    LIMIT 100 OFFSET 20
    """
    stmt = parse(sql)
    assert isinstance(stmt, Select)
    assert stmt.table == "users"
    assert stmt.columns == (
        ColumnRef(name="id"), ColumnRef(name="email"),
    )
    assert stmt.where.op == "AND"
    assert stmt.where.left.op == ">="
    assert stmt.where.right.op == "="
    assert stmt.order_by == (OrderBy(column="id", descending=False),)
    assert stmt.limit == 100
    assert stmt.offset == 20


@pytest.mark.unit
def test_e2e_select_with_aggregate_and_group_by():
    """v0.1 does NOT parse column aliases (``AS``); aggregates and
    GROUP BY are tested directly.  Future batch can add ``AS``."""
    sql = """
    SELECT dept, COUNT(*), AVG(salary)
    FROM employees
    WHERE active = TRUE
    GROUP BY dept
    ORDER BY dept DESC
    LIMIT 10
    """
    stmt = parse(sql)
    assert isinstance(stmt, Select)
    assert stmt.columns == (
        ColumnRef(name="dept"),
        Aggregate(func="COUNT", column="*"),
        Aggregate(func="AVG", column="salary"),
    )
    assert stmt.group_by == ("dept",)
    assert stmt.order_by == (OrderBy(column="dept", descending=True),)
    assert stmt.limit == 10


@pytest.mark.unit
def test_e2e_select_with_is_null_where():
    sql = "SELECT id FROM users WHERE deleted_at IS NULL"
    stmt = parse(sql)
    assert isinstance(stmt, Select)
    assert stmt.where.op == "IS NULL"
    assert stmt.where.operand == ColumnRef(name="deleted_at")


@pytest.mark.unit
def test_e2e_select_with_date_comparison_where():
    """Typed literal in WHERE clause: REQ-TYP-9."""
    sql = """
    SELECT id FROM events
    WHERE occurred_at >= DATE '2026-01-01'
    """
    stmt = parse(sql)
    assert isinstance(stmt, Select)
    assert stmt.where.op == ">="
    assert stmt.where.right == TypedLiteral(
        TypeTag.Date, datetime.date(2026, 1, 1),
    )


@pytest.mark.unit
def test_e2e_update_with_arithmetic_expression():
    sql = "UPDATE products SET price = price * 1.1 WHERE category = 'food'"
    stmt = parse(sql)
    assert isinstance(stmt, Update)
    assert stmt.table == "products"
    assert len(stmt.set_clauses) == 1
    assign = stmt.set_clauses[0]
    assert assign.column == "price"
    assert isinstance(assign.value, BinaryOp)
    assert assign.value.op == "*"


@pytest.mark.unit
def test_e2e_delete_with_compound_where():
    sql = """
    DELETE FROM sessions
    WHERE last_seen < DATE '2025-01-01' OR revoked = TRUE
    """
    stmt = parse(sql)
    assert isinstance(stmt, Delete)
    assert stmt.table == "sessions"
    assert stmt.where.op == "OR"
    assert stmt.where.left.op == "<"
    assert stmt.where.right.op == "="


# --- mixed sanity -------------------------------------------------------


@pytest.mark.unit
def test_e2e_full_crud_lifecycle_parses():
    """Four statements that exercise every DML kind — no execution,
    just confirming the parser can ingest realistic CRUD without
    hand-holding."""
    sqls = [
        "CREATE TABLE notes (id INT PRIMARY KEY, body TEXT)",
        "INSERT INTO notes (id, body) VALUES (1, 'hello')",
        "SELECT * FROM notes WHERE id = 1",
        "UPDATE notes SET body = 'world' WHERE id = 1",
        "DELETE FROM notes WHERE id = 1",
        "DROP TABLE notes",
    ]
    parsed = [parse(s) for s in sqls]
    assert isinstance(parsed[0], CreateTable)
    assert isinstance(parsed[1], Insert)
    assert isinstance(parsed[2], Select)
    assert isinstance(parsed[3], Update)
    assert isinstance(parsed[4], Delete)
    assert isinstance(parsed[5], DropTable)


@pytest.mark.unit
def test_e2e_select_star_with_limit_only():
    """The simplest realistic SELECT — exercises Star + LIMIT path."""
    stmt = parse("SELECT * FROM t LIMIT 5")
    assert isinstance(stmt, Select)
    assert stmt.columns == (Star(),)
    assert stmt.limit == 5
    assert stmt.offset is None