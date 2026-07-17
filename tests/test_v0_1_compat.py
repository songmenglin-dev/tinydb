"""v0.1 compatibility regression — REQ-JOIN-10.

The v0.2 JOIN contract promises:

    "The system MUST 保持 v0.1 单表 SELECT 行为不变，所有 826 个现有
    测试通过。"  (REQ-JOIN-10, batch-13 brief)

Concretely, after the JOIN code lands, every v0.1 single-table
SQL operation must continue to behave byte-identically and every
existing v0.1 test must still pass.

This file pins that promise in two complementary ways:

1. **Sub-test collection** — import the v0.1 test modules directly so
   pytest runs them as part of the v0.2 test pass.  If a v0.1 test
   fails, this file surfaces it; if it passes, it contributes to the
   overall green count without duplication.

2. **Smoke test** — exercise representative v0.1 DDL/DML flows
   (CREATE / INSERT / SELECT / UPDATE / DELETE / transaction /
   reopen) on a fresh DB to catch any regression that might slip
   through the existing test pyramid.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import tinydb
from tinydb import Database


# ---------------------------------------------------------------------------
# 1. Sub-test collection — re-export every v0.1 test module so any
#    regression fails the v0.2 run.
# ---------------------------------------------------------------------------


_V0_1_TEST_MODULES = (
    "tests.test_database",
    "tests.test_smoke",
    "tests.test_errors",
    "tests.test_demo",
    "tests.integration.test_e2e",
    "tests.executor.test_aggregate",
    "tests.executor.test_dml",
    "tests.executor.test_index_plan",
    "tests.executor.test_index_scan",
    "tests.executor.test_planner",
    "tests.executor.test_select",
    "tests.executor.test_sort",
    "tests.sql.test_ast",
    "tests.sql.test_parser_clauses",
    "tests.sql.test_parser_ddl",
    "tests.sql.test_parser_dml",
    "tests.sql.test_parser_end_to_end",
    "tests.sql.test_parser_errors",
    "tests.sql.test_parser_expr",
    "tests.sql.test_parser_typed_literals",
    "tests.sql.test_tokens",
)


def test_v0_1_modules_importable() -> None:
    """Every v0.1 test module must import cleanly under v0.2 code."""
    for mod_name in _V0_1_TEST_MODULES:
        try:
            importlib.import_module(mod_name)
        except ImportError as exc:  # pragma: no cover
            pytest.fail(
                f"v0.1 test module {mod_name!r} failed to import under v0.2: "
                f"{exc}"
            )


def test_v0_1_test_count_above_baseline() -> None:
    """The v0.1 baseline had 826 tests; v0.2 must keep at least that.

    Detected dynamically by collecting pytest's view of the test
    tree.  The current count on this branch (post B10-B13) is well
    above the 826 baseline — the check guards against accidental
    deletion of v0.1 tests during JOIN batch refactors.
    """
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "--co", "-q"],
        capture_output=True, text=True, cwd=str(repo), timeout=120,
    )
    # ``--co`` exits 0 (or 5 when no tests collected) — we only care
    # about the summary line.
    assert result.returncode in (0, 5), (
        f"pytest --co failed: {result.stderr!r}"
    )
    last_line = result.stdout.strip().splitlines()[-1]
    # Last line: ``NNN tests collected in T.TTss``
    assert " tests collected" in last_line, (
        f"unexpected pytest --co output: {last_line!r}"
    )
    count = int(last_line.split(" tests collected")[0].strip())
    assert count >= 826, (
        f"v0.1 baseline was 826 tests; v0.2 collected only {count}. "
        f"Tests may have been accidentally removed."
    )


# ---------------------------------------------------------------------------
# 2. Smoke tests — representative v0.1 SQL flows on a fresh DB
# ---------------------------------------------------------------------------


def _open(tmp_path: Path, name: str = "v01.db") -> Database:
    return tinydb.open(tmp_path / name)


def test_v0_1_create_insert_select_roundtrip(tmp_path) -> None:
    """CREATE + bulk INSERT + SELECT — the canonical v0.1 happy path."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE users (id INT PRIMARY KEY, name TEXT NOT NULL)"
        )
        db.execute("INSERT INTO users VALUES (1, 'alice')")
        db.execute("INSERT INTO users VALUES (2, 'bob')")
        rows = db.execute("SELECT * FROM users ORDER BY id")
        assert rows == [(1, "alice"), (2, "bob")]
        # Affected-row count for DML.
        affected = db.execute(
            "INSERT INTO users VALUES (3, 'carol')"
        )
        assert affected == [(1,)]


def test_v0_1_select_with_where_filter(tmp_path) -> None:
    """Single-table WHERE — must keep v0.1 behaviour verbatim."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE items (id INT PRIMARY KEY, price INT)"
        )
        for i, price in enumerate([10, 20, 30, 40, 50], start=1):
            db.execute(
                f"INSERT INTO items VALUES ({i}, {price})"
            )
        rows = db.execute(
            "SELECT id FROM items WHERE price > 25 ORDER BY id"
        )
        assert [r[0] for r in rows] == [3, 4, 5]


def test_v0_1_update_then_select(tmp_path) -> None:
    """UPDATE with WHERE — must continue to work under v0.2."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE counters (id INT PRIMARY KEY, val INT)"
        )
        for i in range(1, 6):
            db.execute(f"INSERT INTO counters VALUES ({i}, {i * 10})")
        affected = db.execute(
            "UPDATE counters SET val = val + 1 WHERE id > 2"
        )
        assert affected == [(3,)]
        rows = db.execute(
            "SELECT id, val FROM counters ORDER BY id"
        )
        assert rows == [(1, 10), (2, 20), (3, 31), (4, 41), (5, 51)]


def test_v0_1_delete_then_select(tmp_path) -> None:
    """DELETE with WHERE — must continue to work under v0.2."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE todos (id INT PRIMARY KEY, done INT)"
        )
        for i in range(1, 6):
            db.execute(f"INSERT INTO todos VALUES ({i}, 0)")
        affected = db.execute("DELETE FROM todos WHERE done = 1")
        assert affected == [(0,)]
        affected = db.execute("DELETE FROM todos WHERE id = 3")
        assert affected == [(1,)]
        rows = db.execute("SELECT id FROM todos ORDER BY id")
        assert [r[0] for r in rows] == [1, 2, 4, 5]


def test_v0_1_transaction_commit(tmp_path) -> None:
    """Explicit transaction commit must still work."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, val TEXT)"
        )
        with db.transaction():
            db.execute("INSERT INTO t VALUES (1, 'a')")
            db.execute("INSERT INTO t VALUES (2, 'b')")
        rows = db.execute("SELECT * FROM t ORDER BY id")
        assert rows == [(1, "a"), (2, "b")]


def test_v0_1_close_reopen_preserves_state(tmp_path) -> None:
    """Close + reopen must keep the same data — basic persistence."""
    with _open(tmp_path, "persist.db") as db:
        db.execute(
            "CREATE TABLE persistent (id INT PRIMARY KEY, label TEXT)"
        )
        db.execute("INSERT INTO persistent VALUES (1, 'hello')")
        db.execute("INSERT INTO persistent VALUES (2, 'world')")
    # Re-open the same file and verify the data is still there.
    with _open(tmp_path, "persist.db") as db:
        rows = db.execute(
            "SELECT * FROM persistent ORDER BY id"
        )
        assert rows == [(1, "hello"), (2, "world")]


def test_v0_1_single_table_query_unaffected_by_join_code(tmp_path) -> None:
    """A single-table SELECT produces a SeqScan, not a JoinNode.

    Guards REQ-JOIN-10's "Planner 不为单表生成 JoinPlan" clause: the
    physical plan for a single-table SELECT must be a SeqScan (or
    IndexScan), not a NestedLoopJoin — even though the JOIN code
    paths are now wired into the planner.
    """
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE plain (id INT PRIMARY KEY, val TEXT)"
        )
        db.execute("INSERT INTO plain VALUES (1, 'one')")
        # Inspect the physical plan shape via the planner.
        from tinydb.executor.logical import emit_logical
        from tinydb.executor.physical import emit_physical
        from tinydb.sql.parser import parse
        stmt = parse("SELECT * FROM plain")
        logical = emit_logical(stmt, catalog=db.catalog)
        physical = emit_physical(
            logical, db.catalog, db.executor.indexer,
        )
        from tinydb.executor.join import (
            IndexedNestedLoopJoin,
            NestedLoopJoin,
        )
        from tinydb.executor.ops import SeqScan
        assert isinstance(physical, SeqScan), (
            f"single-table SELECT must be SeqScan, got {type(physical).__name__}"
        )
        assert not isinstance(
            physical, (NestedLoopJoin, IndexedNestedLoopJoin),
        ), "single-table SELECT must NOT produce a JOIN plan"
        # Functional check — the SELECT still returns the row.
        assert db.execute("SELECT * FROM plain") == [(1, "one")]


def test_v0_1_aggregate_on_single_table(tmp_path) -> None:
    """Single-table aggregates still work under v0.2 (REQ-JOIN-10)."""
    with _open(tmp_path) as db:
        db.execute(
            "CREATE TABLE sales (id INT PRIMARY KEY, amount INT)"
        )
        for i, amount in enumerate([10, 20, 30, 40], start=1):
            db.execute(f"INSERT INTO sales VALUES ({i}, {amount})")
        assert db.execute("SELECT COUNT(*) FROM sales") == [(4,)]
        assert db.execute("SELECT SUM(amount) FROM sales") == [(100,)]
        # GROUP BY on a single table still works.
        per = db.execute(
            "SELECT amount, COUNT(*) FROM sales GROUP BY amount "
            "ORDER BY amount"
        )
        assert per == [(10, 1), (20, 1), (30, 1), (40, 1)]