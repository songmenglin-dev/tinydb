"""``python -m tinydb`` entry point (T-8.5).

Routes argv through :func:`tinydb.cli.main`, which either runs one SQL
statement (with ``-c``), enters the REPL (no ``-c``), or exits cleanly
on ``--version`` / ``--help``.
"""
from __future__ import annotations

import sys

from tinydb.cli import main

if __name__ == "__main__":
    sys.exit(main())