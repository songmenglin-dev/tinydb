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

    # Maximum source line length copied verbatim into a snippet.  Lines
    # longer than this are truncated so that the error message stays
    # readable regardless of how far the user has wandered horizontally.
    _SNIPPET_LINE_MAX: int = 120

    def __init__(self, line: int, col: int, msg: str) -> None:
        self.line = line
        self.col = col
        self.msg = msg
        super().__init__(f"line {line}, col {col}: {msg}")

    def snippet(self, source: str) -> str:
        """Return a human-friendly two-line excerpt of ``source``.

        Line 1: the offending source line (truncated past
        ``_SNIPPET_LINE_MAX`` characters).
        Line 2: a caret (``^``) anchored at the offending column.

        Useful for CLI error output; raises no error if ``line`` /
        ``col`` fall past end-of-source (defensive: lexer / parser
        positions are usually in-bounds but the snippet helper must
        never crash on its own).
        """
        lines = source.splitlines()
        if self.line < 1 or self.line > len(lines):
            return f"line {self.line}, col {self.col}: {self.msg}"
        text = lines[self.line - 1]
        if len(text) > self._SNIPPET_LINE_MAX:
            text = text[: self._SNIPPET_LINE_MAX - 1] + "…"
        # 1-indexed col → 0-indexed caret offset; clamp to line length.
        caret_col = max(0, min(self.col - 1, len(text)))
        return f"{text}\n{' ' * caret_col}^"


class ConstraintViolation(TinydbError):
    """A write was rejected by a UNIQUE / PRIMARY KEY / CHECK constraint."""


class NotNullViolation(ConstraintViolation):
    """A NOT NULL column received a NULL value."""


class TypeMismatchError(TinydbError):
    """A value could not be coerced to the column's declared type.

    Raised by :mod:`tinydb.types.coerce` when the supplied Python value
    is outside the allowed coercion set (see REQ-TYP-6).
    """


class BTreeOverflowError(TinydbError):
    """Raised by the B-tree write path when an entry would not fit in
    the remaining bytes of a page.

    The insert path catches this signal and re-tries after
    redistributing the data across two pages.  Defined in
    :mod:`tinydb.errors` so the leaf and internal (de)serialisers can
    raise it without creating a circular import into
    :mod:`tinydb.index.btree`.
    """


class WALCorruptionError(TinydbError):
    """Raised when a WAL frame CRC32 does not match its contents.

    Indicates the file was tampered with or written by an incompatible
    encoder.  Defined in :mod:`tinydb.errors` so the WAL implementation
    can raise it without creating a circular import into
    :mod:`tinydb.tx`.
    """


__all__ = [
    "TinydbError",
    "ParseError",
    "ConstraintViolation",
    "NotNullViolation",
    "TypeMismatchError",
    "BTreeOverflowError",
    "WALCorruptionError",
]
