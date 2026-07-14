"""Tests for tinydb.cli.repl meta-commands (T-8.4).

Covers:
1. .exit -> run_repl returns 0, prints goodbye.
2. .quit -> alias; returns 0.
3. .help -> prints help text.
4. .tables -> prints each table name from catalog.
5. .schema -> prints full CREATE TABLE statement per table.
6. Unknown .foo -> "unknown command" message; REPL doesn't exit.
"""
from __future__ import annotations

from typing import List

from tinydb.api import Database
from tinydb.cli.repl import run_repl


def _make_db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


def _step_input(items: List[object]):
    """Build a fake input_fn that walks ``items``, raising EOFError on sentinel."""
    it = iter(items)

    def fake(prompt: str) -> str:
        item = next(it)
        if item is StopIteration:
            raise EOFError
        return item  # type: ignore[return-value]

    return fake


def test_dot_exit_returns_zero(tmp_path) -> None:
    """.exit -> run_repl returns 0, prints goodbye."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        run_repl(
            db,
            input_fn=_step_input([".exit"]),
            output=captured.append,
        )
        joined = "\n".join(captured)
        assert "bye" in joined.lower() or "goodbye" in joined.lower()
    finally:
        db.close()


def test_dot_quit_returns_zero(tmp_path) -> None:
    """.quit -> alias of .exit; returns 0."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        run_repl(
            db,
            input_fn=_step_input([".quit"]),
            output=captured.append,
        )
        joined = "\n".join(captured)
        assert "bye" in joined.lower() or "goodbye" in joined.lower()
    finally:
        db.close()


def test_dot_help_prints_help_text(tmp_path) -> None:
    """.help -> prints help text containing the known commands."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        run_repl(
            db,
            input_fn=_step_input([".help", StopIteration]),
            output=captured.append,
        )
        joined = "\n".join(captured)
        # Help text must mention the core meta-commands.
        assert ".exit" in joined
        assert ".tables" in joined
        assert ".schema" in joined
    finally:
        db.close()


def test_dot_tables_lists_table_names(tmp_path) -> None:
    """.tables -> prints each table name from the catalog."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        db.execute("CREATE TABLE users (id INT PRIMARY KEY)")
        db.execute("CREATE TABLE orders (id INT PRIMARY KEY)")
        run_repl(
            db,
            input_fn=_step_input([".tables", StopIteration]),
            output=captured.append,
        )
        joined = "\n".join(captured)
        assert "users" in joined
        assert "orders" in joined
    finally:
        db.close()


def test_dot_schema_dumps_create_table(tmp_path) -> None:
    """.schema -> prints CREATE TABLE statement per table."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        db.execute("CREATE TABLE widgets (id INT PRIMARY KEY, name TEXT)")
        run_repl(
            db,
            input_fn=_step_input([".schema", StopIteration]),
            output=captured.append,
        )
        joined = "\n".join(captured)
        # Reconstructed CREATE TABLE includes the table name + column decls.
        assert "widgets" in joined
        assert "CREATE TABLE" in joined.upper()
    finally:
        db.close()


def test_unknown_meta_command_prints_error(tmp_path) -> None:
    """Unknown .foo -> 'unknown command' message; REPL does NOT exit."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        # Unknown, then EOF.  REPL must keep going until EOF.
        run_repl(
            db,
            input_fn=_step_input([".foo", StopIteration]),
            output=captured.append,
        )
        joined = "\n".join(captured)
        assert "unknown" in joined.lower()
    finally:
        db.close()