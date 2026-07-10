"""tinydb — lightweight embedded relational database for Python.

Public surface:

- :data:`__version__` — package version string.
- :func:`open` — factory introduced in T-7.1.
- Public exception classes (re-exported from :mod:`tinydb.errors`).
"""

from tinydb._version import __version__
from tinydb.errors import (
    ConstraintViolation,
    NotNullViolation,
    ParseError,
    TinydbError,
    TypeMismatchError,
)

__all__ = [
    "__version__",
    "TinydbError",
    "ParseError",
    "ConstraintViolation",
    "NotNullViolation",
    "TypeMismatchError",
]
