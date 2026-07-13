"""Argparse dispatcher for the tinydb CLI (T-8.1, wired in T-8.5).

Modes:
- ``python -m tinydb --db <path> -c '<sql>'`` → run one SQL and exit.
- ``python -m tinydb --db <path>`` → enter REPL (T-8.3 + T-8.4).
- ``python -m tinydb --help`` / ``--version`` → argparse standard exits.

``main()`` returns a process exit code; ``tinydb/__main__.py`` calls
``sys.exit(main())``.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from tinydb._version import __version__
from tinydb.api import Database
from tinydb.cli.format import format_rows
from tinydb.errors import ParseError, TinydbError


def build_parser() -> argparse.ArgumentParser:
    """Construct the ArgumentParser used by :func:`parse_args`."""
    parser = argparse.ArgumentParser(
        prog="tinydb",
        description=(
            "tinydb — lightweight embedded relational database. "
            "Run a single SQL statement with -c, or omit it for the REPL."
        ),
    )
    parser.add_argument("--db", default=None,
                        help="Path to the database file (created if missing).")
    parser.add_argument("-c", "--command", default=None,
                        help="Run a single SQL statement and exit.")
    parser.add_argument("--version", action="store_true",
                        help="Print the tinydb version and exit.")
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse argv; --version without --db short-circuits to SystemExit(0)."""
    parser = build_parser()
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    if "--version" in raw and "--db" not in raw:
        print(__version__)
        raise SystemExit(0)
    ns = parser.parse_args(argv)
    if ns.db is None:
        parser.error("the following arguments are required: --db")
    return ns


def main(argv: Optional[List[str]] = None) -> int:
    """Dispatch argv → one SQL, REPL, or --version."""
    ns = parse_args(argv)
    if ns.version:
        print(__version__)
        return 0
    with Database(ns.db) as db:
        if ns.command is not None:
            return _run_one(db, ns.command)
        from tinydb.cli.repl import run_repl  # defer import
        return run_repl(db)
    return 0


def _run_one(db: Database, sql: str) -> int:
    """Execute one SQL statement; print rows or error; return exit code."""
    try:
        rows = db.execute(sql)
    except ParseError as exc:
        print(f"ParseError: {exc.msg} (line {exc.line}, col {exc.col})",
              file=sys.stderr)
        return 1
    except TinydbError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if rows:
        print(format_rows(rows))
    return 0


__all__ = ["build_parser", "parse_args", "main"]