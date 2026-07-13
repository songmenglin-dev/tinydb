"""Tests for tinydb.cli.repl — REPL core (T-8.3).

Covers:
1. Single-line "SELECT 1;" -> output formatted as table.
2. Multiple SQL lines execute in order.
3. Empty line -> no-op.
4. Invalid SQL -> ParseError message.
5. EOFError from input_fn -> returns 0.
6. INSERT shows affected count.

The REPL is invoked by ``run_repl`` with injected ``input_fn`` and
``output`` so tests stay isolated from real stdin/stdout.
"""
from __future__ import annotations

from typing import List

import pytest

from tinydb.api import Database
from tinydb.cli.repl import run_repl


def _make_db(tmp_path) -> Database:
    """Helper: open a fresh DB at tmp_path/t.db."""
    return Database(tmp_path / "t.db")


def test_select_outputs_table(tmp_path) -> None:
    """Single-line SELECT outputs the result as a formatted table."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        # input_fn: CREATE table, INSERT one row, SELECT, then EOF.
        inputs = iter(
            [
                "CREATE TABLE t (id INT PRIMARY KEY, name TEXT);",
                "INSERT INTO t VALUES (1, 'alice');",
                "SELECT * FROM t;",
                StopIteration,
            ]
        )

        def fake_input(prompt: str) -> str:
            item = next(inputs)
            if item is StopIteration:
                raise EOFError
            return item

        rc = run_repl(db, input_fn=fake_input, output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        # Executor returns list[tuple] without column names; the REPL
        # renders them via format_rows, which auto-generates col0/col1.
        assert "col0" in joined
        assert "alice" in joined
    finally:
        db.close()


def test_multiple_sql_lines_execute_in_order(tmp_path) -> None:
    """CREATE + INSERT + SELECT executed in order."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        script = iter(
            [
                "CREATE TABLE t (id INT PRIMARY KEY, name TEXT);",
                "INSERT INTO t VALUES (1, 'alice');",
                "SELECT * FROM t;",
                "",  # empty -> no-op
                StopIteration,
            ]
        )

        def step_input(prompt: str) -> str:
            item = next(script)
            if item is StopIteration:
                raise EOFError
            return item

        rc = run_repl(db, input_fn=step_input, output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        assert "alice" in joined
    finally:
        db.close()


def test_empty_line_is_noop(tmp_path) -> None:
    """Empty line -> loop continues, no output produced."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        # First empty -> no-op, then EOF.
        inputs = iter(["", "", StopIteration])

        def fake_input(prompt: str) -> str:
            item = next(inputs)
            if item is StopIteration:
                raise EOFError
            return item

        rc = run_repl(db, input_fn=fake_input, output=captured.append)
        assert rc == 0
        # No output beyond the banner.
        assert captured == [] or all(
            "tinydb v0.1 REPL" in line for line in captured
        )
    finally:
        db.close()


def test_invalid_sql_prints_parse_error(tmp_path) -> None:
    """ParseError -> formatted message; loop continues."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        inputs = iter(["NOT VALID SQL AT ALL", StopIteration])

        def fake_input(prompt: str) -> str:
            item = next(inputs)
            if item is StopIteration:
                raise EOFError
            return item

        rc = run_repl(db, input_fn=fake_input, output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        assert "ParseError" in joined or "parse" in joined.lower()
    finally:
        db.close()


def test_eof_returns_zero(tmp_path) -> None:
    """EOFError on first input -> returns 0."""
    db = _make_db(tmp_path)
    try:

        def fake_input(prompt: str) -> str:
            raise EOFError

        rc = run_repl(db, input_fn=fake_input, output=lambda _: None)
        assert rc == 0
    finally:
        db.close()


def test_insert_shows_affected_count(tmp_path) -> None:
    """INSERT -> output reports affected row count."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        # CREATE, then INSERT, then EOF.
        inputs = iter(
            [
                "CREATE TABLE t (id INT PRIMARY KEY);",
                "INSERT INTO t VALUES (42);",
                StopIteration,
            ]
        )

        def fake_input(prompt: str) -> str:
            item = next(inputs)
            if item is StopIteration:
                raise EOFError
            return item

        rc = run_repl(db, input_fn=fake_input, output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        # DML returns [(affected,)] — expect 1 to appear in the rendered table.
        assert "1" in joined
    finally:
        db.close()