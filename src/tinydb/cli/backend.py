"""Backend abstraction for the dual-mode CLI (v0.3).

A :class:`Backend` exposes the same SQL execution surface whether the
CLI is connected to an in-process :class:`tinydb.api.Database` (the
``--file`` mode) or to a remote server (the ``--uri`` mode).

The contract is intentionally tiny: just enough to dispatch one SQL
statement and return a normalised result.  The CLI's existing
formatting helpers consume the result via the same path.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from tinydb.api import Database
from tinydb.client.sync import Client
from tinydb.errors import TinydbError


@dataclass
class BackendResult:
    """The minimum the CLI needs to format a result.

    ``columns`` may be empty for DML results that don't carry a
    SELECT header.
    """

    rows: List[tuple]
    columns: List[str]
    column_types: List[str]
    elapsed: float
    rowcount: int
    is_select: bool


class Backend(ABC):
    """Abstract SQL execution backend."""

    @abstractmethod
    def execute(self, sql: str) -> BackendResult:
        """Execute one SQL statement; raise :class:`TinydbError` on failure."""

    @abstractmethod
    def close(self) -> None:
        """Release backend resources."""


class FileBackend(Backend):
    """In-process backend wrapping a :class:`Database`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def execute(self, sql: str) -> BackendResult:
        import time as _time
        from tinydb.executor.ops import result_columns
        from tinydb.executor.planner import plan as _plan
        from tinydb.sql.ast import CreateTable, DropTable, Select
        from tinydb.sql.parser import parse

        t0 = _time.perf_counter()
        stmt = parse(sql)
        is_select = isinstance(stmt, Select)
        columns: Optional[List[str]] = None
        types: List[str] = []
        if isinstance(stmt, (CreateTable, DropTable)):
            self._db.execute(sql)
            elapsed = _time.perf_counter() - t0
            return BackendResult(
                rows=[], columns=[], column_types=[], elapsed=elapsed,
                rowcount=0, is_select=False,
            )
        if is_select:
            try:
                columns = result_columns(
                    _plan(stmt, self._db.catalog, self._db.executor.indexer)
                )
            except TinydbError:
                columns = None
            if columns:
                from tinydb.types.system import TypeTag
                meta = self._db.catalog.get_table(stmt.table)
                name_to_type = {c.name: c.tag.name for c in meta.columns}
                types = []
                from tinydb.sql.ast import Star
                for col in stmt.columns:
                    if isinstance(col, Star):
                        types.extend(c.tag.name for c in meta.columns)
                        continue
                    name = getattr(col, "name", None)
                    types.append(name_to_type.get(name, "TEXT") if name else "TEXT")
        rows = self._db.execute(sql)
        elapsed = _time.perf_counter() - t0
        if not rows and not is_select:
            # DML: affected count is in rows[0][0]
            return BackendResult(
                rows=[], columns=[], column_types=[], elapsed=elapsed,
                rowcount=int(rows[0][0]) if rows else 0, is_select=False,
            )
        if not is_select:
            return BackendResult(
                rows=[], columns=[], column_types=[], elapsed=elapsed,
                rowcount=int(rows[0][0]) if rows else 0, is_select=False,
            )
        return BackendResult(
            rows=list(rows), columns=columns or [], column_types=types,
            elapsed=elapsed, rowcount=len(rows), is_select=True,
        )

    def close(self) -> None:
        self._db.close()


class RemoteBackend(Backend):
    """Backend wrapping a remote :class:`tinydb.client.sync.Client`."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def execute(self, sql: str) -> BackendResult:
        import time as _time
        from tinydb.protocol.errors import SyntaxError as SqlSyntaxError
        from tinydb.protocol.errors import GeneralException
        from tinydb.protocol.errors import DataException

        t0 = _time.perf_counter()
        try:
            result = self._client.execute(sql)
        except (SqlSyntaxError, GeneralException, DataException) as e:
            # Translate to TinydbError-style for the CLI.
            # NOTE: bare ``SyntaxError`` would shadow Python's builtin at
            # this scope because the import above aliases the wire-protocol
            # class.  We use the alias explicitly here.
            from tinydb.errors import TinydbError
            raise TinydbError(str(e)) from e
        elapsed = _time.perf_counter() - t0
        # Heuristic: SELECT has columns and rows; INSERT/UPDATE/DELETE
        # don't.  We can't distinguish perfectly without parsing, but
        # ``columns`` is empty when the server returned RESULT_DONE.
        is_select = bool(result.columns)
        return BackendResult(
            rows=[tuple(r) for r in result.rows],
            columns=result.columns,
            column_types=[],  # server doesn't supply type info in v0.3
            elapsed=elapsed,
            rowcount=result.rowcount,
            is_select=is_select,
        )

    def close(self) -> None:
        self._client.close()


__all__ = [
    "Backend",
    "BackendResult",
    "FileBackend",
    "RemoteBackend",
]