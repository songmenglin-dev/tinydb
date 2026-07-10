"""Public exception hierarchy for tinydb.

All tinydb-specific exceptions derive from :class:`TinydbError`, so user
code can write a single ``except tinydb.TinydbError`` to catch anything
the library raises.  Subclasses carry more semantic meaning and let
callers react differently (e.g. a UI layer can show "duplicate key" for
:class:`ConstraintViolation` while a CLI can show "syntax error" for
:class:`ParseError`).

Error categories
----------------

- :class:`ParseError`     — SQL parser failure; carries 1-based ``line``
  and ``col`` of the offending token (REQ-SQL-7).
- :class:`ConstraintViolation` — a write was rejected by a schema
  constraint (UNIQUE, PRIMARY KEY, type mismatch during commit).
- :class:`NotNullViolation` — a NOT NULL column received NULL; a
  subclass of :class:`ConstraintViolation` so callers can choose to
  catch either.
- :class:`TypeMismatchError` — Python value does not match the column's
  declared type and cannot be coerced under REQ-TYP-6.
"""


class TinydbError(Exception):
    """Base class for every exception raised by tinydb."""


class ParseError(TinydbError):
    """Raised by the SQL parser when input cannot be turned into an AST.

    Parameters
    ----------
    line, col:
        1-based position of the offending token in the original SQL
        string.  ``(1, 1)`` means "at the very start".
    msg:
        Human-readable description of the failure.
    """

    def __init__(self, line: int, col: int, msg: str) -> None:
        self.line = line
        self.col = col
        self.msg = msg
        super().__init__(f"line {line}, col {col}: {msg}")


class ConstraintViolation(TinydbError):
    """A write was rejected by a UNIQUE / PRIMARY KEY / CHECK constraint."""


class NotNullViolation(ConstraintViolation):
    """A NOT NULL column received a NULL value."""


class TypeMismatchError(TinydbError):
    """A value could not be coerced to the column's declared type.

    Raised by :mod:`tinydb.types.coerce` when the supplied Python value
    is outside the allowed coercion set (see REQ-TYP-6).
    """


__all__ = [
    "TinydbError",
    "ParseError",
    "ConstraintViolation",
    "NotNullViolation",
    "TypeMismatchError",
]
