"""``python -m tinydb.cli`` entry point.

Thin wrapper that hands control to :func:`tinydb.cli.main`.
"""
from __future__ import annotations

import sys

from tinydb.cli import main

if __name__ == "__main__":
    sys.exit(main())