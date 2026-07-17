"""tinydb — lightweight embedded relational database for Python.

Public surface:

- :data:`__version__` — package version string.
- :class:`Database` — the user-facing facade (T-7.1).
- :class:`IsolationLevel` — READ_COMMITTED / SERIALIZABLE enum (v0.2).
- :func:`open` — factory returning :class:`Database` (T-7.1).
- Public exception classes (re-exported from :mod:`tinydb.errors`).
"""

from tinydb._version import __version__
from tinydb.api import Database, IsolationLevel, open
from tinydb.errors import (
    ConstraintViolation,
    NotNullViolation,
    ParseError,
    TinydbError,
    TypeMismatchError,
)

__all__ = [
    "__version__",
    "Database",
    "IsolationLevel",
    "open",
    "TinydbError",
    "ParseError",
    "ConstraintViolation",
    "NotNullViolation",
    "TypeMismatchError",
]
