"""Command dispatcher for the server (v0.3, T-2.3).

Given a decoded protocol message and a Database handle, return the
list of response frames the server should emit.
"""
from __future__ import annotations

from typing import List, Optional

from tinydb.errors import (
    ConstraintViolation,
    NotNullViolation,
    ParseError,
    TinydbError,
    TypeMismatchError,
)
from tinydb.protocol.frame import Frame
from tinydb.protocol.messages import (
    Exec,
    MessageType,
    ParamType,
    Query,
    ResultDone,
    ResultError,
    ResultHeader,
    ResultRow,
)
from tinydb.protocol.errors import (
    ConnectionException,
    DataException,
    GeneralException,
    SyntaxError,
)
from tinydb.sql.ast import CreateTable, DropTable, Select
from tinydb.sql.parser import parse as parse_sql


# Status flags carried in RESULT_DONE.payload[16].  Defined as named
# constants so callers don't sprinkle raw 0x01 / 0x05 magic numbers
# throughout the dispatcher.
STATUS_FLAGS_OK: int = 0x01           # no further work expected
STATUS_FLAGS_DML: int = 0x05          # at least one row was affected
STATUS_FLAGS_EMPTY: int = STATUS_FLAGS_OK


def _to_param_list(params) -> list:
    """Convert protocol :class:`Param` objects to Python values."""
    out = []
    for p in params:
        if p.type == ParamType.NULL:
            out.append(None)
        elif p.type == ParamType.INT64:
            out.append(p.value)
        elif p.type == ParamType.FLOAT64:
            out.append(p.value)
        elif p.type == ParamType.STRING:
            out.append(p.value)
        elif p.type == ParamType.BOOL:
            out.append(p.value)
        else:
            out.append(p.value)
    return out


def _format_value(v) -> str:
    """Render a Python value as a SQL literal for ?-substitution."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    # string: escape single quotes by doubling them.
    return "'" + str(v).replace("'", "''") + "'"


def _substitute_params(sql: str, params: list) -> str:
    """Replace ``?`` placeholders in ``sql`` with formatted values.

    Implements a proper string-literal state machine so SQL's ``''``
    escape (a doubled single quote inside a literal) does not flip
    the in-string flag and so ``?`` placeholders inside literals are
    left untouched.
    """
    out: list[str] = []
    pi = 0
    in_string = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            if ch == "'":
                # Either end of literal (``'``) or escaped quote
                # (``''`` — two apostrophes together).
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_string = False
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "?" and pi < len(params):
            out.append(_format_value(params[pi]))
            pi += 1
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _classify(sql: str) -> str:
    """Return 'select', 'ddl', 'dml', or 'txn' based on the first keyword.

    Falls back to "dml" when the SQL doesn't start with a recognised
    verb so the executor can produce a useful error message via its
    own parser.
    """
    upper = sql.strip().split(None, 1)[0:1]
    if not upper:
        return "dml"
    head = upper[0].upper()
    if head in ("CREATE", "DROP", "ALTER"):
        return "ddl"
    if head == "SELECT":
        return "select"
    if head in ("INSERT", "UPDATE", "DELETE"):
        return "dml"
    if head in ("BEGIN", "COMMIT", "ROLLBACK"):
        return "txn"
    return "dml"


def _map_error(exc: Exception) -> ResultError:
    """Translate a Database exception to the corresponding wire error frame."""
    if isinstance(exc, ParseError):
        return ResultError(code="42000", msg=f"syntax error: {exc.msg}")
    if isinstance(exc, (ConstraintViolation, NotNullViolation)):
        return ResultError(code="22000", msg=str(exc))
    if isinstance(exc, TypeMismatchError):
        return ResultError(code="22000", msg=str(exc))
    if isinstance(exc, TinydbError):
        return ResultError(code="HY000", msg=str(exc))
    return ResultError(code="HY000", msg=str(exc))


def _rows_to_frames(rows: list, kind: str, *, guess_columns: bool) -> List[Frame]:
    """Build the wire response frames for a Database.execute() result.

    ``kind`` selects the framing:
      * ``ddl``  → just a single RESULT_DONE.
      * ``dml``  → RESULT_DONE with the affected-row count.
      * ``select`` → RESULT_HEADER + RESULT_ROW* + RESULT_DONE.

    ``guess_columns`` chooses how to label columns:
      * ``True``  → derive ``(name, type_code)`` from the first row
        (used by QUERY, where the executor hasn't pre-classified
        values).
      * ``False`` → label columns ``col{i}`` with a string type code
        (used by EXEC, where the server only emits the row stream
        without re-typing each value).
    """
    if kind == "ddl":
        return [ResultDone(rowcount=0, last_insert_id=0, status_flags=STATUS_FLAGS_OK).to_frame()]
    if kind == "dml":
        affected = int(rows[0][0]) if rows else 0
        return [
            ResultDone(
                rowcount=affected,
                last_insert_id=0,
                status_flags=STATUS_FLAGS_DML,
            ).to_frame()
        ]
    # SELECT (or anything else we treat as a row stream).
    if not rows:
        return [
            ResultHeader(columns=[]).to_frame(),
            ResultRow(values=[]).to_frame(),
            ResultDone(rowcount=0, last_insert_id=0, status_flags=STATUS_FLAGS_OK).to_frame(),
        ]
    if guess_columns:
        columns = [
            (f"col{i}", _guess_type_code(v)) for i, v in enumerate(rows[0])
        ]
    else:
        columns = [(f"col{i}", ParamType.STRING.value) for i in range(len(rows[0]))]
    out: List[Frame] = [ResultHeader(columns=columns).to_frame()]
    for row in rows:
        out.append(ResultRow(values=list(row)).to_frame())
    out.append(
        ResultDone(
            rowcount=len(rows), last_insert_id=0, status_flags=STATUS_FLAGS_OK
        ).to_frame()
    )
    return out


async def dispatch_message(msg, db) -> List[Frame]:
    """Route a decoded message to the appropriate Database call.

    Returns the list of response frames the server should send.
    """
    if isinstance(msg, Query):
        return dispatch_query(msg, db)
    if isinstance(msg, Exec):
        return dispatch_exec(msg, db)
    raise GeneralException(f"unhandled message type: {type(msg).__name__}")


def _dispatch_sql(sql: str, db, *, guess_columns: bool) -> List[Frame]:
    """Shared implementation for QUERY and EXEC.

    Both call paths funnel through here so error mapping and result
    framing stay consistent.  ``guess_columns`` is the only knob that
    varies between them (QUERY has untyped Python rows; EXEC has
    already been bound to typed parameters).
    """
    if not sql or not sql.strip():
        return [ResultError(code="42000", msg="empty SQL").to_frame()]
    kind = _classify(sql)
    try:
        rows = db.execute(sql)
    except Exception as e:
        return [_map_error(e).to_frame()]
    return _rows_to_frames(rows, kind, guess_columns=guess_columns)


def dispatch_query(msg: Query, db) -> List[Frame]:
    """Handle a QUERY frame: SQL with no parameters."""
    return _dispatch_sql(msg.sql, db, guess_columns=True)


def dispatch_exec(msg: Exec, db) -> List[Frame]:
    """Handle an EXEC frame: SQL + typed parameters.

    Parameters are rendered back into the SQL string via
    :func:`_substitute_params` so the existing Database.execute(sql)
    path can be reused unchanged.
    """
    params = _to_param_list(msg.params)
    substituted = _substitute_params(msg.sql, params)
    return _dispatch_sql(substituted, db, guess_columns=False)


def _guess_type_code(value) -> int:
    """Best-effort wire type code for a Python value."""
    if value is None:
        return ParamType.NULL.value
    if isinstance(value, bool):
        return ParamType.BOOL.value
    if isinstance(value, int):
        return ParamType.INT64.value
    if isinstance(value, float):
        return ParamType.FLOAT64.value
    # str + everything else fall through to STRING.  This is the same
    # default the codec uses for unknown wire types, so a round-trip
    # stays lossless.
    return ParamType.STRING.value


__all__ = ["dispatch_message", "dispatch_query", "dispatch_exec"]
