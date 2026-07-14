"""End-to-end tests for `python -m tinydb ...` (T-8.5).

Subprocess-driven to exercise the actual ``__main__`` entry point.
Each test uses a fresh DB file in tmp_path so they don't share state.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(*args: str) -> subprocess.CompletedProcess:
    """Invoke ``python -m tinydb`` with the given argv."""
    return subprocess.run(
        [sys.executable, "-m", "tinydb", *args],
        capture_output=True,
        text=True,
    )


def test_create_table_via_main(tmp_path: Path) -> None:
    """`python -m tinydb --db ... -c 'CREATE TABLE ...'` -> exit 0."""
    db_path = tmp_path / "x.db"
    cp = _run(
        "--db",
        str(db_path),
        "-c",
        "CREATE TABLE t (id INT PRIMARY KEY)",
    )
    assert cp.returncode == 0, cp.stderr
    # DB file created on disk.
    assert db_path.exists()


def test_insert_then_select_via_main(tmp_path: Path) -> None:
    """Two -c invocations: CREATE+INSERT, then SELECT -> row appears."""
    db_path = tmp_path / "x.db"
    cp1 = _run(
        "--db",
        str(db_path),
        "-c",
        "CREATE TABLE t (id INT PRIMARY KEY, name TEXT)",
    )
    assert cp1.returncode == 0, cp1.stderr
    cp2 = _run(
        "--db",
        str(db_path),
        "-c",
        "INSERT INTO t VALUES (1, 'alice')",
    )
    assert cp2.returncode == 0, cp2.stderr
    cp3 = _run("--db", str(db_path), "-c", "SELECT * FROM t")
    assert cp3.returncode == 0, cp3.stderr
    assert "alice" in cp3.stdout


def test_invalid_sql_exits_nonzero(tmp_path: Path) -> None:
    """Invalid SQL via -c -> nonzero exit + ParseError on stderr."""
    db_path = tmp_path / "x.db"
    cp = _run(
        "--db",
        str(db_path),
        "-c",
        "NOT VALID SQL AT ALL",
    )
    assert cp.returncode != 0
    # Either 'ParseError' or 'parse' should appear in stderr/stdout.
    combined = cp.stdout + cp.stderr
    assert "parse" in combined.lower() or "Error" in combined


def test_help_exits_zero() -> None:
    """--help -> exit 0 with help text on stdout."""
    cp = _run("--db", "/tmp/anywhere.db", "--help")
    assert cp.returncode == 0
    assert "--db" in cp.stdout
    assert "--command" in cp.stdout or "-c" in cp.stdout


def test_missing_db_exits_two(tmp_path: Path) -> None:
    """Missing --db -> exit 2 (argparse convention)."""
    cp = _run("-c", "SELECT 1")
    assert cp.returncode == 2


def test_version_exits_zero() -> None:
    """--version -> exit 0 + version string."""
    cp = _run("--version")
    assert cp.returncode == 0
    # Version is something like "0.1.0".
    assert "0.1" in cp.stdout