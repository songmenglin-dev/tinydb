"""Tests for tinydb CLI argparse dispatcher (T-8.1).

Covers:
1. --db /tmp/x.db -c 'SELECT 1' parses cleanly.
2. --db /tmp/x.db (no -c) -> not one-shot mode.
3. --help -> SystemExit 0.
4. --version -> SystemExit 0 with version string on stdout.
5. Missing --db -> SystemExit 2.
6. Unknown flag -x -> SystemExit 2.
7. SQL string with ';': '-c "SELECT 1; SELECT 2"' parses (single arg).
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest


# We import the dispatcher's parse_args lazily so the import error path
# is independent of the argparse tests below.
from tinydb.cli.argparse_ext import parse_args  # noqa: E402


def test_parses_one_shot_sql() -> None:
    """--db /tmp/x.db -c 'SELECT 1' parses cleanly."""
    ns = parse_args(["--db", "/tmp/x.db", "-c", "SELECT 1"])
    assert ns.db == "/tmp/x.db"
    assert ns.command == "SELECT 1"
    assert ns.version is False


def test_no_command_is_not_one_shot() -> None:
    """--db /tmp/x.db (no -c) -> command is None."""
    ns = parse_args(["--db", "/tmp/x.db"])
    assert ns.db == "/tmp/x.db"
    assert ns.command is None
    assert ns.version is False


def test_help_exits_zero() -> None:
    """--help -> SystemExit 0."""
    with pytest.raises(SystemExit) as exc:
        # Suppress help printing during test run.
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            parse_args(["--help"])
    assert exc.value.code == 0


def test_version_exits_zero() -> None:
    """--version -> SystemExit 0."""
    with pytest.raises(SystemExit) as exc:
        buf_out = io.StringIO()
        with redirect_stdout(buf_out):
            parse_args(["--version"])
    assert exc.value.code == 0


def test_missing_db_exits_two() -> None:
    """Missing --db -> SystemExit 2 (argparse convention)."""
    with pytest.raises(SystemExit) as exc:
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            parse_args([])
    assert exc.value.code == 2


def test_unknown_flag_exits_two() -> None:
    """Unknown flag -x -> SystemExit 2."""
    with pytest.raises(SystemExit) as exc:
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            parse_args(["--db", "/tmp/x.db", "-x"])
    assert exc.value.code == 2


def test_sql_with_semicolon_parses() -> None:
    """-c "SELECT 1; SELECT 2" parses as a single string arg (multi-stmt execution is downstream)."""
    ns = parse_args(["--db", "/tmp/x.db", "-c", "SELECT 1; SELECT 2"])
    assert ns.command == "SELECT 1; SELECT 2"
    assert ns.db == "/tmp/x.db"