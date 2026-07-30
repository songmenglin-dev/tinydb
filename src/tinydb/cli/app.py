"""High-level CLI application dispatcher (v0.3, T-4.5).

The actual argv parsing lives in :mod:`tinydb.cli.argparse_ext`; this
module wraps that entry point with a clean ``run()`` function so
embedders (tests, IDE integrations) can invoke the CLI without
shelling out.

Three modes are supported:

* ``--file PATH`` — embedded mode (in-process :class:`Database`).
* ``--uri tinydb://host:port/db`` — remote mode (TCP client).
* Neither flag — :func:`main` raises ``SystemExit`` via argparse.

``run()`` returns the process exit code.
"""
from __future__ import annotations

import sys
from typing import List, Optional

from tinydb.cli.argparse_ext import main as _argparse_main


def run(argv: Optional[List[str]] = None) -> int:
    """Run the CLI with ``argv`` (defaults to ``sys.argv[1:]``)."""
    return _argparse_main(argv)


def main() -> int:  # pragma: no cover - convenience wrapper
    """``python -m tinydb`` entry point."""
    return run()


__all__ = ["run", "main"]