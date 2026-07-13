"""Argparse dispatcher for the tinydb CLI (T-8.1).

Three modes:
- ``python -m tinydb --db <path> -c '<sql>'`` → run one command, exit.
- ``python -m tinydb --db <path>`` → enter REPL (T-8.3).
- ``python -m tinydb --help`` / ``--version`` → argparse standard exits.

Returns a ``Namespace`` with at least ``db``, ``command``, ``version``.
"""
from __future__ import annotations

import argparse
from typing import List, Optional

from tinydb._version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Construct the ArgumentParser used by :func:`parse_args`.

    ``--db`` is required, except when ``--version`` is the sole flag —
    in that case :func:`parse_args` returns a Namespace with
    ``version=True`` and ``db=None`` so the version path can short-
    circuit without the user supplying a database path.
    """
    parser = argparse.ArgumentParser(
        prog="tinydb",
        description=(
            "tinydb — lightweight embedded relational database. "
            "Run a single SQL statement with -c, or omit it for the REPL."
        ),
    )
    parser.add_argument(
        "--db",
        required=False,
        default=None,
        help="Path to the database file (created if missing).",
    )
    parser.add_argument(
        "-c",
        "--command",
        default=None,
        help="Run a single SQL statement and exit.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the tinydb version and exit.",
    )
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse ``argv`` (or ``sys.argv[1:]`` if ``None``) into a Namespace.

    Enforces ``--db`` *only* when ``--version`` is not requested, and
    raises ``SystemExit(0)`` after printing the version when
    ``--version`` is set — matching the convention used by
    ``sqlite3 --version`` and friends.
    """
    import sys

    parser = build_parser()
    # Pre-flight: did the caller ask for --version?  We check the raw
    # token list so we can short-circuit before the --db requirement.
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    if "--version" in raw and "--db" not in raw:
        # Parse with --db temporarily optional just to capture --version,
        # then exit cleanly — argparse's own action="version" would do
        # this but it would require --db to be optional too, which we
        # can't express conditionally.
        print(__version__)
        raise SystemExit(0)
    ns = parser.parse_args(argv)
    if ns.db is None:
        # Mirror argparse's "the following arguments are required: --db"
        # error so callers see a consistent SystemExit(2).
        parser.error("the following arguments are required: --db")
    return ns


def main(argv: Optional[List[str]] = None) -> int:
    """Top-level entry used by both ``tinydb/__main__.py`` and tests.

    For T-8.1 we only verify the dispatcher; the actual SQL/REPL
    execution is wired in T-8.5.  For now: with ``-c`` we exit 0
    (real execution arrives in T-8.5); without it we exit 0 too (REPL
    arrives in T-8.3).  ``--version`` prints the version and exits 0.
    ``--help`` is handled by argparse.
    """
    ns = parse_args(argv)
    if ns.version:
        print(__version__)
        return 0
    # One-shot SQL execution + REPL routing are added in T-8.3 / T-8.5.
    # The dispatcher shape (db, command, version) is in place.
    return 0


__all__ = ["build_parser", "parse_args", "main"]