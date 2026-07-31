"""Command dispatcher for the server (v0.3, T-2.3).

Given a decoded protocol message and a Database handle, return the
list of response frames the server should emit.
"""
from __future__ import annotations

from typing import List

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
    ResultDone as _RD,
)
from tinydb.protocol.errors import (
    ConnectionException,
    DataException,
    GeneralException,
    SyntaxError,
)
from tinydb.sql.ast import CreateTable, DropTable, Select
from tinydb.sql.parser import parse as parse_sql


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
    """Return 'select', 'ddl', or 'dml' based on the SQL AST.

    Falls back to "select" when the SQL doesn't parse (so a malformed
    query produces a single RESULT_DONE error rather than getting
    mis-classified as DML).
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
    # Unknown - default to "dml" so the executor can produce a useful
    # error message via its own parser.
    return "dml"


async def dispatch_message(msg, db) -> List[Frame]:
    """Route a decoded message to the appropriate Database call.

    Returns the list of response frames the server should send.
    """
    if isinstance(msg, Query):
        return dispatch_query(msg, db)
    if isinstance(msg, Exec):
        return dispatch_exec(msg, db)
    raise GeneralException(f"unhandled message type: {type(msg).__name__}")


def dispatch_query(msg: Query, db) -> List[Frame]:
    if not msg.sql or not msg.sql.strip():
        return [ResultError(code="42000", msg="empty SQL").to_frame()]
    kind = _classify(msg.sql)
    try:
        rows = db.execute(msg.sql)
    except ParseError as e:
        return [ResultError(code="42000", msg=f"syntax error: {e.msg}").to_frame()]
    except (ConstraintViolation, NotNullViolation) as e:
        return [ResultError(code="22000", msg=str(e)).to_frame()]
    except TypeMismatchError as e:
        return [ResultError(code="22000", msg=str(e)).to_frame()]
    except TinydbError as e:
        return [ResultError(code="HY000", msg=str(e)).to_frame()]
    # Normalise rows to list[list] for the wire protocol.
    if kind == "ddl":
        # DDL returns RESULT_DONE only.
        return [
            ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame()
        ]
    if kind == "dml":
        # DML returns [(affected_count,)].
        if rows:
            affected = int(rows[0][0])
        else:
            affected = 0
        return [
            ResultDone(
                rowcount=affected,
                last_insert_id=0,
                status_flags=0x05,
            ).to_frame()
        ]
    # SELECT: send header + rows + done.
    if not rows:
        return [
            ResultHeader(columns=[]).to_frame(),
            ResultRow(values=[]).to_frame(),
            ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame(),
        ]
    columns = [
        (f"col{i}", _guess_type_code(v)) for i, v in enumerate(rows[0])
    ]
    out = [ResultHeader(columns=columns).to_frame()]
    for row in rows:
        out.append(ResultRow(values=list(row)).to_frame())
    out.append(
        ResultDone(
            rowcount=len(rows), last_insert_id=0, status_flags=0x01
        ).to_frame()
    )
    return out


def dispatch_exec(msg: Exec, db) -> List[Frame]:
    """EXEC frame: SQL + typed parameters."""
    params = _to_param_list(msg.params)
    # Substitute ? placeholders with literal values so the existing
    # Database.execute(sql) path can be reused unchanged.
    substituted = _substitute_params(msg.sql, params)
    kind = _classify(substituted)
    try:
        rows = db.execute(substituted)
    except ParseError as pe:
        return [ResultError(code="42000", msg=f"syntax error: {pe.msg}").to_frame()]
    except (ConstraintViolation, NotNullViolation) as cv:
        return [ResultError(code="22000", msg=str(cv)).to_frame()]
    except TypeMismatchError as te:
        return [ResultError(code="22000", msg=str(te)).to_frame()]
    except TinydbError as te:
        return [ResultError(code="HY000", msg=str(te)).to_frame()]
    if kind == "ddl":
        return [
            ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame()
        ]
    if kind == "dml":
        affected = int(rows[0][0]) if rows else 0
        return [
            ResultDone(
                rowcount=affected,
                last_insert_id=0,
                status_flags=0x05,
            ).to_frame()
        ]
    if not rows:
        return [
            ResultHeader(columns=[]).to_frame(),
            ResultRow(values=[]).to_frame(),
            ResultDone(rowcount=0, last_insert_id=0, status_flags=0x01).to_frame(),
        ]
    columns = [(f"col{i}", 0x03) for i in range(len(rows[0]))]
    out = [ResultHeader(columns=columns).to_frame()]
    for row in rows:
        out.append(ResultRow(values=list(row)).to_frame())
    out.append(
        ResultDone(
            rowcount=len(rows), last_insert_id=0, status_flags=0x01
        ).to_frame()
    )
    return out


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
    if isinstance(value, str):
        return ParamType.STRING.value
    return ParamType.STRING.value


__all__ = ["dispatch_message", "dispatch_query", "dispatch_exec"]
