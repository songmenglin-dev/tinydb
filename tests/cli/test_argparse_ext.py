"""Direct unit tests for ``tinydb.cli.argparse_ext.main`` (T-8.5).

The end-to-end ``python -m tinydb`` path is exercised by
``test_main_e2e.py`` via subprocess; this file covers the in-process
``main()`` entry point, which is what subprocess invokes via
``tinydb/__main__.py``.

Goals
-----
- Lift ``tinydb/cli`` coverage above the 80% gate.
- Cover the TinydbError branch in :func:`_run_one` (no easy way to
  trigger through subprocess).
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from tinydb.api import Database
from tinydb.cli import main as cli_main


def test_main_version_prints_version_and_returns_zero(tmp_path: Path) -> None:
    """--version -> main() prints version. parse_args raises SystemExit(0).

    We catch SystemExit so we can assert on the printed version string
    without using subprocess.  ``main()`` therefore does not get a
    chance to return — that is by design (matches ``sqlite3 --version``).
    """
    buf = io.StringIO()
    with redirect_stdout(buf):
        with pytest.raises(SystemExit) as exc:
            cli_main(["--version"])
    assert exc.value.code == 0
    assert "0.1" in buf.getvalue()


def test_main_version_with_db_still_works(tmp_path: Path) -> None:
    """--version together with --db still short-circuits to version path."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli_main(["--db", str(tmp_path / "x.db"), "--version"])
    assert rc == 0
    assert "0.1" in buf.getvalue()


def test_main_runs_one_sql_and_prints_rows(tmp_path: Path) -> None:
    """-c 'CREATE TABLE ... ; INSERT ... ; SELECT * FROM ...' prints rows."""
    db_path = tmp_path / "x.db"
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        rc = cli_main(
            [
                "--db",
                str(db_path),
                "-c",
                "CREATE TABLE t (id INT PRIMARY KEY, name TEXT)",
            ]
        )
        assert rc == 0
        rc = cli_main(
            [
                "--db",
                str(db_path),
                "-c",
                "INSERT INTO t VALUES (1, 'alice')",
            ]
        )
        assert rc == 0
        buf_out.truncate(0); buf_out.seek(0)
        rc = cli_main(["--db", str(db_path), "-c", "SELECT * FROM t"])
        assert rc == 0
    assert "alice" in buf_out.getvalue()


def test_main_invalid_sql_returns_one(tmp_path: Path) -> None:
    """ParseError -> exit code 1 + ParseError on stderr."""
    db_path = tmp_path / "x.db"
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        rc = cli_main(
            [
                "--db",
                str(db_path),
                "-c",
                "NOT VALID SQL AT ALL",
            ]
        )
    assert rc == 1
    assert "ParseError" in buf_err.getvalue()


def test_main_repl_runs_until_exit(tmp_path: Path, monkeypatch) -> None:
    """No -c -> REPL.  Simulate user typing .exit."""
    db_path = tmp_path / "x.db"
    from tinydb.cli import repl as repl_mod

    def fake_input(prompt: str) -> str:
        return ".exit"

    # Patch the ``input`` builtin that the REPL falls back on by
    # default.  ``repl.input`` is a module-level alias resolved at
    # call-time inside ``run_repl``, so we monkeypatch the builtin.
    import builtins
    monkeypatch.setattr(builtins, "input", fake_input)
    rc = cli_main(["--db", str(db_path)])
    assert rc == 0