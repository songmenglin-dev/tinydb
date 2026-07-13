"""tinydb CLI package.

Public surface (re-exported for convenience):

- :func:`parse_args` — argv → :class:`argparse.Namespace`.
- :func:`main` — argv → exit code; the canonical entry point for
  ``python -m tinydb ...`` and subprocess tests.

The actual SQL execution lives in :mod:`tinydb.api`; the CLI is a thin
shell that wires argv parsing, the table formatter, and the REPL.
"""
from __future__ import annotations

from tinydb.cli.argparse_ext import main, parse_args

__all__ = ["main", "parse_args"]