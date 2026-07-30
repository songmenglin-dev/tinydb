"""Allow ``python -m tinydb.server`` to launch the server."""
from __future__ import annotations

import sys

from tinydb.server.app import main

if __name__ == "__main__":
    sys.exit(main())
