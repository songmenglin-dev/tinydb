"""Argparse dispatcher for the tinydb CLI (T-8.1, wired in T-8.5; v0.3 client/server).

Modes:
- ``python -m tinydb --file <path> -c '<sql>'`` → run one SQL and exit.
- ``python -m tinydb --file <path>`` → enter REPL (T-8.3 + T-8.4).
- ``python -m tinydb --uri tinydb://host:port/db -c '<sql>'`` → remote mode.
- ``python -m tinydb --help`` / ``--version`` → argparse standard exits.

``--file`` and ``--uri`` are mutually exclusive.

``main()`` returns a process exit code; ``tinydb/__main__.py`` calls
``sys.exit(main())``.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from tinydb._version import __version__
from tinydb.api import Database
from tinydb.cli.backend import Backend, FileBackend, RemoteBackend
from tinydb.cli.format import format_rows
from tinydb.errors import ParseError, TinydbError
from tinydb.executor.ops import result_columns
from tinydb.executor.planner import plan as _plan
from tinydb.sql.ast import CreateTable, DropTable
from tinydb.sql.parser import parse


def build_parser() -> argparse.ArgumentParser:
    """Construct the ArgumentParser used by :func:`parse_args`."""
    parser = argparse.ArgumentParser(
        prog="tinydb",
        description=(
            "tinydb - lightweight embedded relational database. "
            "Run a single SQL statement with -c, or omit it for the REPL."
        ),
    )
    parser.add_argument("--file", default=None,
                        help="Path to the database file (created if missing).")
    parser.add_argument("--db", default=None,
                        help="Alias for --file (v0.2 compatibility).")
    parser.add_argument("--uri", default=None,
                        help="Remote tinydb URI (tinydb://host:port/db).")
    parser.add_argument("-c", "--command", default=None,
                        help="Run a single SQL statement and exit.")
    parser.add_argument("--version", action="store_true",
                        help="Print the tinydb version and exit.")
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse argv; --version without --file/--uri short-circuits to SystemExit(0)."""
    parser = build_parser()
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    if "--version" in raw and "--file" not in raw and "--uri" not in raw and "--db" not in raw:
        print(__version__)
        raise SystemExit(0)
    ns = parser.parse_args(argv)
    # Resolve --db (v0.2 alias) into --file.
    if ns.db is not None:
        if ns.file is not None:
            parser.error("--db and --file are mutually exclusive")
        ns.file = ns.db
    if ns.file is None and ns.uri is None:
        parser.error(
            "one of the following arguments is required: --file, --db, --uri"
        )
    if ns.file is not None and ns.uri is not None:
        parser.error("--file and --uri are mutually exclusive")
    return ns


def _open_backend(ns: argparse.Namespace) -> Backend:
    """Construct the appropriate backend for the parsed CLI args."""
    if ns.file is not None:
        return FileBackend(Database(ns.file))
    from tinydb.cli.uri import parse_uri
    from tinydb.client.errors import ConnectionError as ClientConnectionError
    from tinydb.client.sync import Client
    uri = parse_uri(ns.uri)
    try:
        return RemoteBackend(Client(uri.host, uri.port, database=uri.database))
    except ClientConnectionError as exc:
        print(f"Error: cannot connect to {uri.host}:{uri.port}: {exc}",
              file=sys.stderr)
        sys.exit(1)


def main(argv: Optional[List[str]] = None) -> int:
    """Dispatch argv -> one SQL, REPL, or --version."""
    ns = parse_args(argv)
    if ns.version:
        print(__version__)
        return 0
    backend = _open_backend(ns)
    try:
        if ns.command is not None:
            return _run_one(backend, ns.command)
        from tinydb.cli.repl import run_repl  # defer import
        # REPL currently expects a Database; pass the wrapped backend.
        return run_repl(backend)
    finally:
        backend.close()


def _run_one(backend: Backend, sql: str) -> int:
    """Execute one SQL statement; print rows / error / 'OK'; return exit code.

    Mirrors the polish from v0.2: DDL prints 'OK'; SELECT prints rows
    with real column names; INSERT/UPDATE/DELETE prints '<n> row(s)'.
    """
    # For DDL detection we need to parse, which requires the SQL surface.
    # The backend already does that internally; we only need a second
    # parse here to tell apart SELECT vs DML.  Cheap enough.
    try:
        stmt = parse(sql)
    except ParseError as exc:
        print(
            f"ParseError: {exc.msg} (line {exc.line}, col {exc.col})",
            file=sys.stderr,
        )
        return 1
    try:
        result = backend.execute(sql)
    except TinydbError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if isinstance(stmt, (CreateTable, DropTable)):
        print("OK")
        return 0
    if not result.is_select:
        print(f"{result.rowcount} row(s)")
        return 0
    if not result.rows:
        return 0
    print(format_rows(result.rows, columns=result.columns))
    return 0


__all__ = ["build_parser", "parse_args", "main"]