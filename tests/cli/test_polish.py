"""T-POLISH: CLI polish — column names + DDL confirmation (POLISH-CLI).

Defects addressed:
1. ``SELECT *`` previously rendered headers as ``col0``/``col1`` instead
   of the real column names from the table schema.  Fix: REPL and the
   one-shot path extract column names from the executed plan tree and
   pass them to ``format_rows``.
2. DDL statements (``CREATE TABLE``, ``DROP TABLE``) returned no output
   so the user had no confirmation.  Fix: REPL and one-shot path
   detect DDL and print ``"OK"``.

Tests cover:
* REPL ``SELECT *`` → real column names in output.
* REPL explicit column list → real names.
* Synthetic columns (expressions) → fallback ``col0/col1`` or
  ``?column?``-style label.
* REPL CREATE/DROP → ``OK`` in output.
* Subprocess one-shot CREATE → exit 0 + ``OK`` in stdout.
"""
from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List

from tinydb.api import Database
from tinydb.cli import main as cli_main
from tinydb.cli.repl import run_repl


# --- helpers -----------------------------------------------------------


def _make_db(tmp_path) -> Database:
    return Database(tmp_path / "t.db")


def _capturing_input(lines: List[str]):
    """Build an input_fn that yields each line then EOF."""
    it = iter(lines)

    def fake_input(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return fake_input


# --- Defect 1: column-name fallback ------------------------------------


def test_select_star_shows_real_column_names(tmp_path) -> None:
    """REPL ``SELECT * FROM user`` shows ``id name``, NOT ``col0 col1``."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        inputs = [
            "CREATE TABLE user (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO user VALUES (1, 'tom');",
            "SELECT * FROM user;",
        ]
        rc = run_repl(db, input_fn=_capturing_input(inputs), output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        # Real column names from the schema should appear as the header row.
        assert "id" in joined
        assert "name" in joined
        # The auto-generated fallback must NOT appear.
        assert "col0" not in joined
        assert "col1" not in joined
    finally:
        db.close()


def test_select_explicit_columns_show_names(tmp_path) -> None:
    """REPL ``SELECT id, name FROM user`` shows ``id name`` header."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        inputs = [
            "CREATE TABLE user (id INT PRIMARY KEY, name TEXT);",
            "INSERT INTO user VALUES (7, 'alice');",
            "SELECT id, name FROM user;",
        ]
        rc = run_repl(db, input_fn=_capturing_input(inputs), output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        assert "id" in joined
        assert "name" in joined
        assert "col0" not in joined
        assert "col1" not in joined
    finally:
        db.close()


def test_select_expression_falls_back_to_label(tmp_path) -> None:
    """REPL ``SELECT id + 1 FROM t`` uses a synthetic column label.

    The synthesized column name should appear; the worst-case fallback
    ``col0`` is acceptable if the planner doesn't expose a label yet.
    """
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        inputs = [
            "CREATE TABLE t (id INT);",
            "INSERT INTO t VALUES (10);",
            "SELECT id + 1 FROM t;",
        ]
        rc = run_repl(db, input_fn=_capturing_input(inputs), output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        # Either we got a label like "Add" or we fell back to col0;
        # either way, the row body (11) should be present.
        assert "11" in joined
        # And the header should not be empty: at least one header word appears.
        # We just verify the formatter didn't crash and produced output.
        assert joined.strip() != ""
    finally:
        db.close()


# --- Defect 2: DDL confirmation ---------------------------------------


def test_create_table_in_repl_prints_ok(tmp_path) -> None:
    """REPL ``CREATE TABLE x (id INT)`` prints ``OK``."""
    db = _make_db(tmp_path)
    try:
        captured: List[str] = []
        inputs = ["CREATE TABLE x (id INT);"]
        rc = run_repl(db, input_fn=_capturing_input(inputs), output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        assert "OK" in joined
    finally:
        db.close()


def test_drop_table_in_repl_prints_ok(tmp_path) -> None:
    """REPL ``DROP TABLE x`` prints ``OK``."""
    db = _make_db(tmp_path)
    try:
        # Pre-create the table so DROP succeeds.
        db.execute("CREATE TABLE x (id INT)")
        captured: List[str] = []
        inputs = ["DROP TABLE x;"]
        rc = run_repl(db, input_fn=_capturing_input(inputs), output=captured.append)
        assert rc == 0
        joined = "\n".join(captured)
        assert "OK" in joined
    finally:
        db.close()


# --- One-shot path (subprocess) ---------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tinydb", *args],
        capture_output=True,
        text=True,
    )


def test_create_table_via_oneshot_prints_ok(tmp_path: Path) -> None:
    """`python -m tinydb --db x.db -c 'CREATE TABLE ...'` -> exit 0 + OK."""
    db_path = tmp_path / "x.db"
    cp = _run_cli(
        "--db", str(db_path),
        "-c", "CREATE TABLE x (id INT PRIMARY KEY)",
    )
    assert cp.returncode == 0, cp.stderr
    assert "OK" in cp.stdout


def test_drop_table_via_oneshot_prints_ok(tmp_path: Path) -> None:
    """`python -m tinydb --db x.db -c 'DROP TABLE ...'` -> exit 0 + OK."""
    db_path = tmp_path / "x.db"
    # First create the table (OK), then drop (also OK).
    cp1 = _run_cli(
        "--db", str(db_path),
        "-c", "CREATE TABLE x (id INT PRIMARY KEY)",
    )
    assert cp1.returncode == 0
    cp2 = _run_cli(
        "--db", str(db_path),
        "-c", "DROP TABLE x",
    )
    assert cp2.returncode == 0, cp2.stderr
    assert "OK" in cp2.stdout


def test_oneshot_select_star_uses_real_names(tmp_path: Path) -> None:
    """One-shot `SELECT *` after CREATE+INSERT shows real column names."""
    db_path = tmp_path / "x.db"
    _run_cli(
        "--db", str(db_path),
        "-c", "CREATE TABLE t (id INT PRIMARY KEY, name TEXT)",
    )
    _run_cli(
        "--db", str(db_path),
        "-c", "INSERT INTO t VALUES (1, 'alice')",
    )
    cp = _run_cli("--db", str(db_path), "-c", "SELECT * FROM t")
    assert cp.returncode == 0, cp.stderr
    out = cp.stdout
    assert "id" in out
    assert "name" in out
    # The fallback labels must NOT appear.
    assert "col0" not in out
    assert "col1" not in out


def test_oneshot_select_prints_rows(tmp_path: Path) -> None:
    """One-shot SELECT -> exit 0 + row data in stdout (existing behaviour)."""
    db_path = tmp_path / "x.db"
    _run_cli(
        "--db", str(db_path),
        "-c", "CREATE TABLE t (id INT PRIMARY KEY)",
    )
    _run_cli(
        "--db", str(db_path),
        "-c", "INSERT INTO t VALUES (42)",
    )
    cp = _run_cli("--db", str(db_path), "-c", "SELECT * FROM t")
    assert cp.returncode == 0
    assert "42" in cp.stdout